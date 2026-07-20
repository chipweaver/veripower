#!/usr/bin/env bash
# ============================================================================
# fa_core_indep golden runner (§1.3(a) gate wire — adjudicate.py --golden-cmd).
#
# Turns "does this arm's RTL match the held-out golden?" into an exit code:
#   exit 0  == all tiles within tolerance (GOLDEN: PASS)
#   exit !=0 == any tile failed / compile failed / timeout / no marker
# Fail-loud: the verdict is PASS only on positive evidence of the PASS marker.
#
# Generates held-out vectors (reference.py), compiles the arm's RTL + the fixed
# golden TB (VCS, plain SV — no UVM), runs, and greps the marker. The held-out
# seeds are supplied by the adjudicator (--seeds); they are NOT the arms' dev seeds.
#
# Usage (typically from an adjudicate.py sandbox, cwd = the run workdir):
#   golden_run.sh --rtl <rtl_sourcelist> --seeds 7,11,13,17,19 [--causal 0,1] [--work DIR]
#
# STATUS: DRAFT — needs VCS + a conforming DUT to exercise end-to-end.
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RTL=""
SEEDS="1,2,3,4,5"
CAUSAL="0,1"
WORK="./golden_work"

while [[ $# -gt 0 ]]; do
	case "$1" in
	--rtl)
		RTL="$2"
		shift 2
		;;
	--seeds)
		SEEDS="$2"
		shift 2
		;;
	--causal)
		CAUSAL="$2"
		shift 2
		;;
	--work)
		WORK="$2"
		shift 2
		;;
	*)
		echo "golden_run: unknown arg $1" >&2
		exit 2
		;;
	esac
done

[[ -n "$RTL" ]] || {
	echo "golden_run: --rtl <rtl_sourcelist> required" >&2
	exit 2
}
[[ -f "$RTL" ]] || {
	echo "golden_run: rtl sourcelist not found: $RTL" >&2
	exit 2
}
RTL="$(cd "$(dirname "$RTL")" && pwd)/$(basename "$RTL")" # absolute (vcs -f)

mkdir -p "$WORK"
cd "$WORK"

# 1) held-out golden vectors (TB token stream).
python3 "$HERE/reference.py" --seeds "$SEEDS" --causal "$CAUSAL" \
	--format tb --out vectors.tb

# 2) compile arm RTL + the fixed golden TB (plain SV; no UVM).
vcs -full64 -sverilog -timescale=1ns/1ps \
	-f "$RTL" "$HERE/fa_core_indep_golden_tb.sv" \
	-o simv_golden 2>&1 | tee compile.log

# 3) run; PASS marker is the sole positive evidence.
set +e
./simv_golden +VECTORS=vectors.tb -l run.log
set -e

if grep -q "GOLDEN: PASS" run.log; then
	exit 0
fi
echo "golden_run: no PASS marker — see $WORK/run.log" >&2
exit 1
