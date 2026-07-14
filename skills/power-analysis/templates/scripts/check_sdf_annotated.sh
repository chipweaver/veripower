#!/usr/bin/env bash
# Hard SDF back-annotation sanity gate (phase=compile category=sdf), factored out so it is
# unit-testable WITHOUT EDA (see tests/unit/test_check_sdf_annotated.py).
# Two tool-dependent success signatures are accepted:
#   1. a "Number of <X> annotated" count line — must total > 0 (a reported 0 fails);
#   2. the VCS "*** SDF annotation completed" marker — some VCS releases (e.g. L-2016.06)
#      emit begin/completed markers + a "Total errors/warnings" block but NO count line.
# Fails (exit 1) if a count line reports 0 annotated elements, OR if NEITHER a count line
# NOR the completed-marker is found (format drift / no annotation → fail loud, never a
# silent pass on missing data).
set -euo pipefail
log="${1:?usage: check_sdf_annotated.sh <gls-compile-log>}"

# Signature 1: an explicit "Number of <X> annotated" count line, when the tool emits it.
lines=$(grep -iE "Number of [^[:space:]]+ annotated" "$log" || true)
if [ -n "$lines" ]; then
	total=$(printf '%s\n' "$lines" | grep -oE "[0-9]+" | paste -sd+ - | bc 2>/dev/null || echo 0)
	total=${total:-0}
	if [ "$total" -eq 0 ]; then
		echo "[check_sdf_annotated] ERROR: SDF annotated 0 elements (phase=compile category=sdf)" >&2
		exit 1
	fi
	echo "[check_sdf_annotated] OK: SDF annotated $total element(s)"
	exit 0
fi

# Signature 2 (no count line): accept the VCS completion marker. A successful
# $sdf_annotate() prints "*** SDF annotation completed"; a run that began but crashed
# prints "begin" without "completed", so gating on "completed" still fails loud.
if grep -qiE "SDF annotation completed" "$log"; then
	echo "[check_sdf_annotated] OK: SDF annotation completed (tool emitted no count line)"
	exit 0
fi

echo "[check_sdf_annotated] ERROR: no SDF annotation summary line found (phase=compile category=sdf) — log format drift? validate regex against a real gls-compile-log.txt" >&2
exit 1
