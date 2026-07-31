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

[ -f "$PLAN" ] || {
	echo "[run_gls_power] ERROR: --plan not found: $PLAN" >&2
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
	target="$SAIF_DIR/${id}.saif"

	# Stale 0-byte canonical (from a prior aborted run) must NOT be reused —
	# delete and fall through to re-simulate.
	if [ -f "$canonical" ] && [ ! -s "$canonical" ]; then
		echo "[stale] $canonical (size=0); deleting and re-running" | tee -a "$LOG"
		rm -f "$canonical"
	fi

	if [ -f "$canonical" ]; then
		if ! ln -f "$canonical" "$target" 2>/dev/null; then
			cp -p "$canonical" "$target"
		fi
		echo "[reuse] $id ← $seq" | tee -a "$LOG"
		continue
	fi

	echo "[run]   $id ($seq)" | tee -a "$LOG"
	"$SIMV" +UVM_TESTNAME="power_${seq}_test" \
		+saif_file="$canonical" \
		+vcs+initreg+0 \
		2>&1 | tee "$SAIF_DIR/${id}.run.log" >>"$LOG"

	if [ ! -s "$canonical" ]; then
		echo "[FAIL]  $id ($seq) — SAIF empty or missing (phase=run)" | tee -a "$LOG" >&2
		exit 1
	fi

	if ! ln -f "$canonical" "$target" 2>/dev/null; then
		cp -p "$canonical" "$target"
	fi
done < <(python3 "$(dirname "$0")/extract_power_scenarios.py" "$PLAN")

echo "[run_gls_power] all scenarios completed" | tee -a "$LOG"
