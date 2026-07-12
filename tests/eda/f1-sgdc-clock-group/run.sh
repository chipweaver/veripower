#!/usr/bin/env bash
# F1 regression: run SpyGlass CDC on cdc_smoke with two SGDCs and compare.
#   nogroups.sgdc -> expect NO cross-domain CDC violation (vacuous; the bug)
#   groups.sgdc   -> expect a cross-domain CDC violation on a->q (the fix)
# NOTE: that hypothesis did NOT hold on SpyGlass_vL-2016.06 — BOTH variants flag
# Ac_unsync01 identically (see README.md "Result" for the observed record + why).
# Must run under /home/mhc. Reuses the lint-cdc collect_report.py to aggregate.
set -euo pipefail
cd "$(dirname "$0")"
COLLECT="$(git rev-parse --show-toplevel)/skills/lint-cdc/templates/scripts/collect_report.py"

# --- Two environment workarounds confirmed empirically on SpyGlass_vL-2016.06 (see
# README.md "Environment notes"); neither changes the CDC question under test. ---
#
# (1) collect_report.py resolves its output root from its OWN file location
#     (Path(__file__).resolve().parent.parent), assuming it's deployed alongside the run
#     (as the lint-cdc skill does). Invoked here by absolute cross-directory path, that
#     would resolve to skills/lint-cdc/templates/ instead of this fixture. Work around by
#     running a local copy so __file__ resolves correctly; delete it afterward.
#
# (2) SpyGlass_vL-2016.06 fatals at open_project ("found errors in project file", no
#     further detail) when scripts/filelist.txt's sourcelist entry is a RELATIVE path for
#     a small/single-file design (confirmed: identical single-file projects pass/fail on
#     absolute-vs-relative path alone, reproducibly). Work around by rewriting
#     filelist.txt to an absolute path for the run, restoring the committed relative-path
#     content on exit (trap, so it restores even on error) so the tracked file is
#     unchanged in git.
ORIG_FILELIST="$(cat scripts/filelist.txt)"
restore_filelist() { printf '%s' "$ORIG_FILELIST" >scripts/filelist.txt; }
trap restore_filelist EXIT
printf '%s/rtl/cdc_smoke.v\n' "$(pwd)" >scripts/filelist.txt

run_variant() {
	local variant="$1"
	rm -rf spyglass_work cdc-report.txt cdc-violations.json spyglass*.log spyglass*.cmd sg_shell.log
	cp "scripts/${variant}.sgdc" scripts/constraints.sgdc
	spyglass -64bit -shell -tcl scripts/run.tcl
	cp "$COLLECT" scripts/collect_report.py
	python3 scripts/collect_report.py cdc
	rm -f scripts/collect_report.py
	rm -rf scripts/__pycache__
	echo "=== ${variant}: cdc-violations.json ==="
	cat cdc-violations.json
	cp cdc-violations.json "cdc-violations.${variant}.json"
}

run_variant nogroups
run_variant groups

# Leave only the two comparison JSONs; everything else is run residue.
rm -rf spyglass_work spyglass*.log spyglass*.cmd sg_shell.log cdc-report.txt cdc-violations.json scripts/constraints.sgdc

echo
echo "Compare cdc-violations.nogroups.json against cdc-violations.groups.json."
echo "Observed golden result (README.md \"Result\"): BOTH flag Ac_unsync01 identically"
echo "(1 error each) on SpyGlass_vL-2016.06 — the original 'nogroups is vacuously clean'"
echo "hypothesis did not hold. A deviation from that recorded result is the regression."
