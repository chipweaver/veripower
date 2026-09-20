#!/usr/bin/env bash
# VCS compile/run entry modeled after verification/examples/and_gate.
#
# Pass/fail contract: each simv invocation receives +IPD_STATUS_PATH=<path>;
# tb_top writes "PASS" or "FAIL" after run_test returns. The bash
# script reads the status file to decide PASS/FAIL. Missing status file (simv
# exit before UVM completion) → FAIL.
#
# RESULT line format (stable contract consumed by write_summary.py):
#   RESULT <test_id> <PASS|FAIL> \
#          uvm_testname=<name> log=<path>
#
# The token order and keyword names are paired with write_summary.py's load_results(); the
# pairing is checked by tests/unit/test_infra_summary.py, which derives a line from the echo
# below and parses it with the real script rather than trusting this comment.
set -euo pipefail

MODE="${1:-regress}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Withdraw the outputs this command replaces, even when setup fails.
case "$MODE" in
compile | smoke | regress)
	rm -f result.json regression-log.txt case-results.json case-results-summary.md structural-coverage.json
	rm -rf cov_merge
	;;
coverage)
	rm -f result.json structural-coverage.json
	rm -rf cov_merge
	;;
summary)
	rm -f result.json case-results.json case-results-summary.md
	;;
*)
	echo "run_vcs_regression: unknown mode '$MODE'" >&2
	exit 1
	;;
esac

# shellcheck disable=SC1091
source ./env.sh

# VCS_COV is an env-tunable string of vcs coverage flags ("-cm line+cond+branch+tgl+fsm");
# split it into an array so each flag expands as its own properly-quoted argument.
read -ra VCS_COV_ARGS <<<"$VCS_COV"

require_simulation_inputs() {
	: "${UVM_HOME:?run_vcs_regression: export UVM_HOME=/path/to/uvm before compilation or simulation}"

	[[ -d "$UVM_HOME" ]] || {
		echo "run_vcs_regression: UVM_HOME does not exist: $UVM_HOME" >&2
		exit 1
	}

	[[ -f "$TESTLIST_JSON" ]] || {
		echo "run_vcs_regression: missing $TESTLIST_JSON; run sim bootstrap --plan <simulation-plan workdir> first to generate the scaffold (which writes this file)" >&2
		exit 1
	}
}

compile_simv() {
	rm -rf "$SIMV" "$SIMV.daidir" "$COV_DB.vdb" cov_test
	require_simulation_inputs
	mkdir -p "$RUN_LOG_DIR"
	# VCS_CC/VCS_CPP: optional compiler pin (e.g. gcc-4.8 when host gcc defaults to PIE
	# and conflicts with VCS prebuilt non-PIC objects). Unset → VCS picks its built-in default.
	# --allow-shlib-undefined: relax newer binutils strictness about forward refs inside VCS .so libs.
	vcs -full64 -f filelist.f \
		-sverilog \
		-debug_access+all \
		-kdb -lca "${VCS_COV_ARGS[@]}" -cm_dir "$COV_DB" -o "$SIMV" \
		-timescale=1ns/1ps \
		${VCS_CC:+-cc "$VCS_CC"} ${VCS_CPP:+-cpp "$VCS_CPP"} \
		-LDFLAGS "-Wl,--no-as-needed -Wl,--allow-shlib-undefined" \
		-CFLAGS -I"$ROOT/tb/uvm/refmodel" -CFLAGS -std=gnu99 \
		-CFLAGS -DVCS +vpi "${UVM_HOME}/src/dpi/uvm_dpi.cc" \
		-l "$COMPILE_LOG"
}

select_tests() {
	"$PYTHON" "$(dirname "${BASH_SOURCE[0]}")/select_tests.py" "$MODE" "$TESTLIST_JSON"
}

run_selected_tests() {
	require_simulation_inputs
	[[ -x "$SIMV" ]] || {
		echo "run_vcs_regression: missing executable $SIMV; compile with make simv" >&2
		exit 1
	}
	local selected
	if ! selected="$(select_tests)"; then
		echo "run_vcs_regression: no tests selected for mode '$MODE'" >&2
		exit 1
	fi

	mkdir -p "$RUN_LOG_DIR"
	local regression_log="regression-log.txt"
	{
		echo "# suite: $MODE"
		echo "# module: $MODULE"
		echo "# top: $TOP"
		echo "# seed: $SEED"
	} >"$regression_log"

	while IFS='|' read -r test_id uvm_testname; do
		[[ -n "$test_id" ]] || continue
		local test_seed log_path status_path cov_dir cov_name status fsdb_path simv_rc
		test_seed="$SEED"
		log_path="$RUN_LOG_DIR/${test_id}.log"
		status_path="$RUN_LOG_DIR/${test_id}.status"
		cov_dir="$ROOT/cov_test/cov_${uvm_testname}_${test_seed}"
		cov_name="${uvm_testname}_${test_seed}"
		# Full-hierarchy FSDB waveform of this test's run, at the run-dir root
		# (NOT $RUN_LOG_DIR=logs/), where simulation-triage reads it via sim_run.
		# Retained only for failing tests (gc-on-pass below).
		fsdb_path="$ROOT/${test_id}.fsdb"
		# Clear prior status and waveforms; a run must produce its own completion result.
		rm -f "$status_path" "$fsdb_path"
		rm -rf "$cov_dir.vdb"
		# The seed passed to the simulator is the one recorded in the regression log.
		simv_rc=0
		IPD_FSDB_FILE="$fsdb_path" \
			"./$SIMV" +UVM_TESTNAME="$uvm_testname" +IPD_TEST_ID="$test_id" \
			+IPD_STATUS_PATH="$status_path" +ntb_random_seed="$test_seed" \
			"${VCS_COV_ARGS[@]}" -cm_dir "$cov_dir" -cm_name "$cov_name" \
			-ucli -do "$(dirname "${BASH_SOURCE[0]}")/dump.tcl" \
			-l "$log_path" || simv_rc=$?
		[ "$simv_rc" -eq 0 ] || echo "run_vcs_regression: $test_id simv exit $simv_rc (test failed)" >&2
		if [ "$simv_rc" -eq 0 ] && [ -f "$status_path" ] && [ "$(cat "$status_path")" = "PASS" ]; then
			status="PASS"
			rm -f "$fsdb_path" # gc-on-pass: keep an FSDB only for failing tests
		else
			status="FAIL"
		fi
		# RESULT line format is a stable contract — see file header before changing.
		echo "RESULT $test_id $status uvm_testname=$uvm_testname log=$log_path" >>"$regression_log"
	done <<<"$selected"
}

coverage() {
	[[ -f regression-log.txt ]] || {
		echo "run_vcs_regression: no regression log for coverage reporting" >&2
		return 1
	}
	# These databases share the current compilation; compile retires the whole set.
	urg -dir "$COV_DB.vdb" -dir cov_test/*.vdb -report cov_merge -format text
	"$PYTHON" scripts/parse_coverage.py --cov-dir cov_merge --out structural-coverage.json
}

case "$MODE" in
compile)
	compile_simv
	;;
smoke)
	run_selected_tests
	;;
regress)
	run_selected_tests
	# Emit machine-readable structural coverage for the exit gate (fail-loud if unparseable).
	coverage
	;;
coverage)
	coverage
	;;
summary)
	"$PYTHON" scripts/write_summary.py --verification-dir "$ROOT"
	;;
esac
