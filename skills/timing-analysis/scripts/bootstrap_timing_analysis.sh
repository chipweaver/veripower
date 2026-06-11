#!/usr/bin/env bash
# Deploy the timing-analysis templates into the stage's per-run workdir
# (asic/<module>/Design/timing-analysis/runs/<N>/), verify the synthesis
# prerequisite, resolve TOP, and substitute placeholders.
# Invoked by the agent under veripower:timing-analysis; may also be run manually.
#
# Usage:
#   bash ${CLAUDE_SKILL_DIR}/scripts/bootstrap_timing_analysis.sh \
#        --module <module-dir-name> --workdir <abs-path> [--top <top-module>]
#
# When --top is omitted: inferred from the single Design/synthesis/out/<TOP>_syn.v.
set -euo pipefail

usage() {
	echo "Usage: $0 --module <module-dir-name> --workdir <abs-path> [--top <top-module>]" >&2
	echo "  --workdir  per-run workdir abs path; shape asic/<M>/Design/timing-analysis/runs/<N>/." >&2
	echo "  --top      top module; inferred from Design/synthesis/out/<TOP>_syn.v when omitted." >&2
	exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="${SCRIPT_DIR}/../templates"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

MODULE=""
TOP=""
WORKDIR=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--module)
		shift
		[[ $# -gt 0 ]] || usage
		MODULE="$1"
		shift
		;;
	--top)
		shift
		[[ $# -gt 0 ]] || usage
		TOP="$1"
		shift
		;;
	--workdir)
		shift
		[[ $# -gt 0 ]] || usage
		WORKDIR="$1"
		shift
		;;
	-h | --help) usage ;;
	*)
		echo "unknown flag: $1" >&2
		usage
		;;
	esac
done

[[ -n "$MODULE" ]] || usage
[[ -n "$WORKDIR" ]] || {
	echo "bootstrap_timing_analysis: --workdir required" >&2
	usage
}
[[ -d "$TEMPLATE_DIR" ]] || {
	echo "bootstrap_timing_analysis: missing $TEMPLATE_DIR" >&2
	exit 1
}

# Resolve WORKDIR to absolute, then to a tree-root-relative path for the TCL.
if [[ "$WORKDIR" != /* ]]; then WORKDIR="$REPO_ROOT/$WORKDIR"; fi
WORKDIR="${WORKDIR%/}"
WORKDIR_REL="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$WORKDIR" "$REPO_ROOT")"

SYN_DIR="$REPO_ROOT/asic/$MODULE/Design/synthesis"
SYN_RESULT="$SYN_DIR/result.json"

# Prerequisite: synthesis result.json present and status=pass (fail-closed).
[[ -f "$SYN_RESULT" ]] || {
	echo "bootstrap_timing_analysis: missing $SYN_RESULT" >&2
	exit 1
}
STATUS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status",""))' "$SYN_RESULT")"
[[ "$STATUS" == "pass" ]] || {
	echo "bootstrap_timing_analysis: synthesis result.json status=$STATUS (need pass)" >&2
	exit 1
}

# Resolve TOP from the single out/<TOP>_syn.v when not given.
if [[ -z "${TOP:-}" ]]; then
	shopt -s nullglob
	cands=("$SYN_DIR"/out/*_syn.v)
	shopt -u nullglob
	if [[ ${#cands[@]} -eq 1 ]]; then
		base="$(basename "${cands[0]}")"
		TOP="${base%_syn.v}"
	else
		echo "bootstrap_timing_analysis: cannot infer top from $SYN_DIR/out/*_syn.v (${#cands[@]} matches); pass --top" >&2
		exit 1
	fi
fi

# Verify the canonical netlist + SDC the TCL reads.
for f in "$SYN_DIR/out/${TOP}_syn.v" "$SYN_DIR/out/${TOP}_syn.sdc"; do
	[[ -f "$f" ]] || {
		echo "bootstrap_timing_analysis: missing external reference: $f" >&2
		exit 1
	}
done

mkdir -p "$WORKDIR"
if [[ -f "$WORKDIR/run_sta.tcl" ]]; then
	echo "bootstrap_timing_analysis: already deployed (detected $WORKDIR/run_sta.tcl)" >&2
	exit 1
fi

cp -a "$TEMPLATE_DIR/." "$WORKDIR"

# Substitute placeholders. Use '|' as sed delimiter (paths contain '/').
sed -i "s|MY_MODULE|${MODULE}|g; s|MY_WORKDIR|${WORKDIR_REL}|g" "$WORKDIR/run_sta.tcl"

LIB_DB_VALUE="${LIB_DB:-FILL_IN_LIB_DB_PATH}"
sed -i "s|MY_TOP|${TOP}|g; s|FILL_IN_LIB_DB_PATH|${LIB_DB_VALUE}|g" "$WORKDIR/config.tcl"

echo "bootstrap_timing_analysis: deployed $WORKDIR (TOP=$TOP, LIB_DB=$LIB_DB_VALUE)"
echo "  Next: ensure LIB_DB is set in $WORKDIR/config.tcl, then from the tree root:"
echo "        pt_shell -f $WORKDIR_REL/run_sta.tcl"
