#!/usr/bin/env bash
# Hard SDF back-annotation sanity gate (phase=compile category=sdf), factored out so it is
# unit-testable WITHOUT EDA (see tests/unit/test_check_sdf_annotated.py).
# Fails (exit 1) if VCS reports 0 annotated elements, OR if no annotation-summary
# line is found at all (format drift → fail loud so the regex gets fixed, never a
# silent pass on missing data). VALIDATE the regex below against a real
# gls-compile-log.txt before relying on this gate.
set -euo pipefail
log="${1:?usage: check_sdf_annotated.sh <gls-compile-log>}"

lines=$(grep -iE "Number of [^[:space:]]+ annotated" "$log" || true)
if [ -z "$lines" ]; then
	echo "[check_sdf_annotated] ERROR: no SDF annotation summary line found (phase=compile category=sdf) — log format drift? validate regex against a real gls-compile-log.txt" >&2
	exit 1
fi

total=$(printf '%s\n' "$lines" | grep -oE "[0-9]+" | paste -sd+ - | bc 2>/dev/null || echo 0)
total=${total:-0}
if [ "$total" -eq 0 ]; then
	echo "[check_sdf_annotated] ERROR: SDF annotated 0 elements (phase=compile category=sdf)" >&2
	exit 1
fi
echo "[check_sdf_annotated] OK: SDF annotated $total element(s)"
