#!/usr/bin/env bash
# Iterate the plan dir's power-scenarios.json, run simv per
# scenario, and emit one SAIF per scenario. Dedup by sequence_ref via
# hardlink (or copy fallback).
set -euo pipefail

PLAN=""
SAIF_DIR=""
SIMV=""
LOG=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--plan)
		PLAN="$2"
		shift 2
		;;
	--saif-dir)
		SAIF_DIR="$2"
		shift 2
		;;
	--simv)
		SIMV="$2"
		shift 2
		;;
	--log)
		LOG="$2"
		shift 2
		;;
	*)
		echo "unknown flag: $1" >&2
		exit 2
		;;
	esac
done

# All four args are required; set -u doesn't catch set-to-empty, so check explicitly.
[ -n "$PLAN" ] || {
	echo "[run_gls_power] ERROR: --plan required" >&2
	exit 2
}
[ -n "$SAIF_DIR" ] || {
	echo "[run_gls_power] ERROR: --saif-dir required" >&2
	exit 2
}
[ -n "$SIMV" ] || {
	echo "[run_gls_power] ERROR: --simv required" >&2
	exit 2
}
[ -n "$LOG" ] || {
	echo "[run_gls_power] ERROR: --log required" >&2
	exit 2
}

# --plan is the simulation-plan STAGE ROOT, not a file: extract_power_scenarios.py reads
# power-scenarios.json out of it. It was a single scaffold-specification.json before the
# plan split into sidecars, and this guard kept testing for a file afterwards — which no
# caller passes, so gls-run could not start on any module.
[ -d "$PLAN" ] || {
	echo "[run_gls_power] ERROR: --plan is not a directory: $PLAN" >&2
	exit 1
}
if [ "${SIMV#./}" != "$SIMV" ] || [ "${SIMV#/}" != "$SIMV" ]; then
	[ -x "$SIMV" ] || {
		echo "[run_gls_power] ERROR: --simv not executable: $SIMV" >&2
		exit 1
	}
else
	command -v "$SIMV" >/dev/null 2>&1 || {
		echo "[run_gls_power] ERROR: --simv not in PATH: $SIMV" >&2
		exit 1
	}
fi

mkdir -p "$SAIF_DIR/_dedup"
: >"$LOG"

while IFS=$'\t' read -r id seq; do
	[ -z "$id" ] && continue

	canonical="$SAIF_DIR/_dedup/${seq}.saif"
	canonical_status="$SAIF_DIR/_dedup/${seq}.status"
	target="$SAIF_DIR/${id}.saif"
	target_status="$SAIF_DIR/${id}.status"

	# Stale 0-byte canonical (from a prior aborted run) must NOT be reused —
	# delete and fall through to re-simulate. A canonical SAIF with no status file
	# beside it is the same case: the two are one record of one run, and activity
	# whose run reported no verdict is not inheritable by the scenarios sharing it.
	if [ -f "$canonical" ] && { [ ! -s "$canonical" ] || [ ! -f "$canonical_status" ]; }; then
		echo "[stale] $canonical (empty, or no status beside it); deleting and re-running" | tee -a "$LOG"
		rm -f "$canonical" "$canonical_status"
	fi

	if [ -f "$canonical" ]; then
		if ! ln -f "$canonical" "$target" 2>/dev/null; then
			cp -p "$canonical" "$target"
		fi
		if ! ln -f "$canonical_status" "$target_status" 2>/dev/null; then
			cp -p "$canonical_status" "$target_status"
		fi
		echo "[reuse] $id ← $seq" | tee -a "$LOG"
		continue
	fi

	# Write-fresh-or-nothing: an inherited status file would report the previous run.
	# base_test writes it in report_phase from the UVM report server's own UVM_ERROR +
	# UVM_FATAL counts, so a run that died before that phase leaves none — and its absence
	# is the signal, exactly as in the RTL regression this TB is shared with.
	rm -f "$canonical_status"
	echo "[run]   $id ($seq)" | tee -a "$LOG"
	"$SIMV" +UVM_TESTNAME="power_${seq}_test" \
		+saif_file="$canonical" \
		+IPD_STATUS_PATH="$canonical_status" \
		+vcs+initreg+0 \
		2>&1 | tee "$SAIF_DIR/${id}.run.log" >>"$LOG"

	if [ ! -s "$canonical" ]; then
		echo "[FAIL]  $id ($seq) — SAIF empty or missing (phase=run)" | tee -a "$LOG" >&2
		exit 1
	fi

	if ! ln -f "$canonical" "$target" 2>/dev/null; then
		cp -p "$canonical" "$target"
	fi
	# Not gated here: every scenario runs, and finalize reads the whole set, so one
	# scenario's UVM errors do not cost the account of the others.
	if [ -f "$canonical_status" ]; then
		ln -f "$canonical_status" "$target_status" 2>/dev/null || cp -p "$canonical_status" "$target_status"
	fi
done < <(python3 "$(dirname "$0")/extract_power_scenarios.py" "$PLAN")

echo "[run_gls_power] all scenarios completed" | tee -a "$LOG"
