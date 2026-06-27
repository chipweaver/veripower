#!/usr/bin/env bash
# VCS compile/run entry modeled after verification/examples/and_gate.
#
# Pass/fail contract: each simv invocation receives +IPD_STATUS_PATH=<path>;
# base_test.sv::report_phase writes "PASS" or "FAIL" to that file. The bash
# script reads the status file to decide PASS/FAIL/MANUAL_REVIEW. Missing
# status file (simv crash before report_phase) → FAIL.
#
# RESULT line format (stable contract consumed by write_summary.py):
#   RESULT <test_id> <PASS|FAIL|MANUAL_REVIEW> feature=<feature_id> class=<class> \
#          uvm_testname=<name> log=<path>
#
# DO NOT change the token order or keyword names without also updating
# write_summary.py load_results() and ipd-stage-sim/references/artifact-contract.md.
set -euo pipefail

MODE="${1:-regress}"
REQUESTED_TEST="${2:-}"
# Space-separated test_ids to mark as MANUAL_REVIEW instead of FAIL.
# Agent can pass this after exhausting retry budget.
MANUAL_REVIEW_IDS="${MANUAL_REVIEW_IDS:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source ./env.sh

# VCS_COV is an env-tunable string of vcs coverage flags ("-cm line+cond+branch+tgl+fsm");
# split it into an array so each flag expands as its own properly-quoted argument.
read -ra VCS_COV_ARGS <<<"$VCS_COV"

[[ -n "${UVM_HOME:-}" ]] || {
	echo "run_vcs_regression: UVM_HOME not set; export UVM_HOME=/path/to/uvm first" >&2
	exit 1
}

[[ -d "$UVM_HOME" ]] || {
	echo "run_vcs_regression: UVM_HOME does not exist: $UVM_HOME" >&2
	exit 1
}

[[ -f "$TESTLIST_JSON" ]] || {
	echo "run_vcs_regression: missing $TESTLIST_JSON; run sim bootstrap --scaffold <scaffold-specification.json> first to generate the scaffold (which writes this file)" >&2
	exit 1
}

compile_simv() {
	mkdir -p "$RUN_LOG_DIR"
	# VCS_CC/VCS_CPP: optional compiler pin (e.g. gcc-4.8 when host gcc defaults to PIE
	# and conflicts with VCS prebuilt non-PIC objects). Unset → VCS picks its built-in default.
	# --allow-shlib-undefined: relax newer binutils strictness about forward refs inside VCS .so libs.
	vcs -full64 -f filelist.f \
		-sverilog \
		-debug_access+all \
		-kdb -lca "${VCS_COV_ARGS[@]}" \
		-timescale=1ns/1ps \
		${VCS_CC:+-cc "$VCS_CC"} ${VCS_CPP:+-cpp "$VCS_CPP"} \
		-LDFLAGS "-Wl,--no-as-needed -Wl,--allow-shlib-undefined" \
		-CFLAGS -DVCS +vpi "${UVM_HOME}/src/dpi/uvm_dpi.cc" \
		-l "$COMPILE_LOG"
}

select_tests() {
	"$PYTHON" "$(dirname "${BASH_SOURCE[0]}")/select_tests.py" \
		"$MODE" "$REQUESTED_TEST" "$TESTLIST_JSON"
}

run_selected_tests() {
	local selected
	if ! selected="$(select_tests)"; then
		if [[ "$MODE" == "single" ]]; then
			echo "run_vcs_regression: test '$REQUESTED_TEST' not found" >&2
		else
			echo "run_vcs_regression: no tests selected for mode '$MODE'" >&2
		fi
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

	while IFS='|' read -r test_id uvm_testname feature_id test_class; do
		[[ -n "$test_id" ]] || continue
		local test_seed log_path status_path cov_dir cov_name status
		test_seed="$SEED"
		log_path="$RUN_LOG_DIR/${test_id}.log"
		status_path="$RUN_LOG_DIR/${test_id}.status"
		cov_dir="$ROOT/cov_test/cov_${uvm_testname}_${test_seed}"
		cov_name="${uvm_testname}_${test_seed}"
		# Pre-clean: missing status file after simv = FAIL (catches simv crash
		# before report_phase runs).
		rm -f "$status_path"
		"./$SIMV" +UVM_TESTNAME="$uvm_testname" +IPD_TEST_ID="$test_id" \
			+IPD_STATUS_PATH="$status_path" \
			"${VCS_COV_ARGS[@]}" -cm_dir "$cov_dir" -cm_name "$cov_name" \
			-l "$log_path"
		if [ -f "$status_path" ] && [ "$(cat "$status_path")" = "PASS" ]; then
			status="PASS"
		else
			# Check if this test_id has been designated for manual review.
			if [[ -n "$MANUAL_REVIEW_IDS" ]] && echo " $MANUAL_REVIEW_IDS " | grep -qF " $test_id "; then
				status="MANUAL_REVIEW"
			else
				status="FAIL"
			fi
		fi
		# RESULT line format is a stable contract — see file header before changing.
		echo "RESULT $test_id $status feature=$feature_id class=$test_class uvm_testname=$uvm_testname log=$log_path" >>"$regression_log"
	done <<<"$selected"
}

case "$MODE" in
compile)
	compile_simv
	;;
smoke)
	[[ -x "./$SIMV" ]] || compile_simv
	run_selected_tests
	;;
regress)
	[[ -x "./$SIMV" ]] || compile_simv
	run_selected_tests
	# Emit machine-readable structural coverage for the exit gate (fail-loud if unparseable).
	make coverage
	;;
single)
	[[ -n "$REQUESTED_TEST" ]] || {
		echo "run_vcs_regression: single mode requires TEST=test_id or TEST=uvm_testname" >&2
		exit 1
	}
	[[ -x "./$SIMV" ]] || compile_simv
	run_selected_tests
	;;
*)
	echo "run_vcs_regression: unknown mode '$MODE' (expected compile|smoke|regress|single)" >&2
	exit 1
	;;
esac
