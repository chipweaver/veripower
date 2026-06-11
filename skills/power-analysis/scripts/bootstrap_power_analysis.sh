#!/usr/bin/env bash
# Bootstrap power-analysis stage's per-run workdir
# (asic/<module>/Verification/power-analysis/runs/<N>/, provided by the caller)
# by copying templates and substituting MY_TOP, then rendering UVM power tests
# from Verification/simulation-plan/scaffold-specification.json's power_scenarios[].
set -euo pipefail

usage() {
	echo "Usage: $0 --module <module> --workdir <abs path> [--top <top>]" >&2
	echo "" >&2
	echo "  --workdir  power-analysis stage's per-run workdir abs path (provided by the caller)." >&2
	echo "             Shape: asic/<M>/Verification/power-analysis/runs/<N>/." >&2
	echo "             Templates and emit_power_tests.py output land in this directory." >&2
	echo "  --top      Top-level module name (auto-inferred from Design/rtl-design/filelist.txt if omitted)" >&2
	exit 2
}

MODULE=""
TOP=""
WORKDIR=""

while [[ $# -gt 0 ]]; do
	case "$1" in
	--module)
		MODULE="$2"
		shift 2
		;;
	--top)
		TOP="$2"
		shift 2
		;;
	--workdir)
		WORKDIR="$2"
		shift 2
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
	echo "bootstrap_power_analysis: --workdir required" >&2
	usage
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [[ "$WORKDIR" != /* ]]; then
	WORKDIR="$REPO_ROOT/$WORKDIR"
fi
WORKDIR="${WORKDIR%/}"
DEST="$WORKDIR"

mkdir -p "$DEST"
# Workdir may be pre-created by the caller (possibly with sibling files like
# orchestrator-context.md); only treat workdir as "already deployed" if Makefile exists.
if [[ -f "$DEST/Makefile" ]]; then
	echo "bootstrap_power_analysis: already deployed (detected $DEST/Makefile)" >&2
	echo "  To redeploy, back up and remove $DEST/{Makefile,scripts,scaffold} first." >&2
	exit 1
fi

# Infer TOP from rtl-design/filelist.txt first line if not provided.
# Canonical implementation — matches bootstrap_synthesis.sh's infer_top_from_filelist:
# skips +/- directive lines and rejects non-identifier basenames.
infer_top_from_filelist() {
	local f="$REPO_ROOT/asic/$MODULE/Design/rtl-design/filelist.txt"
	[[ -f "$f" ]] || return 0
	local first
	first=$(grep -v '^[[:space:]]*#' "$f" 2>/dev/null |
		grep -v '^[[:space:]]*$' |
		grep -Ev '^[[:space:]]*[+\-]' |
		head -1 | tr -d '\r' || true)
	[[ -n "$first" ]] || return 0
	local base
	base=$(basename "$first")
	base="${base%.v}"
	base="${base%.sv}"
	base="${base%.vh}"
	[[ "$base" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 0
	echo "$base"
}

if [[ -z "$TOP" ]]; then
	TOP="$(infer_top_from_filelist)"
fi

if [[ -z "$TOP" ]]; then
	echo "bootstrap_power_analysis: cannot infer --top; pass explicitly" >&2
	exit 1
fi

cp -R "$SKILL_DIR/templates/." "$DEST/"

# Compute relpaths from workdir to the three external reference directories,
# so env.sh stays correct regardless of workdir depth (runs/<N>/ vs canonical).
SYN_OUT_DIR="$REPO_ROOT/asic/$MODULE/Design/synthesis/out"
SIM_DIR="$REPO_ROOT/asic/$MODULE/Verification/simulation"
PLAN_DIR="$REPO_ROOT/asic/$MODULE/Verification/simulation-plan"

# Pre-flight: upstream stages must have produced their canonical artifacts
# before power-analysis bootstrap can succeed. Fail-fast with actionable
# messages rather than reporting "Deployed" and letting `make` fail opaquely.
SYN_NETLIST="$SYN_OUT_DIR/${TOP}_syn.v"
SIM_FILELIST="$SIM_DIR/filelist.f"
if [[ ! -f "$SYN_NETLIST" ]]; then
	echo "bootstrap_power_analysis: synthesis netlist not found: $SYN_NETLIST" >&2
	echo "  Run synthesis stage first; see skills/synthesis/SKILL.md." >&2
	exit 1
fi
if [[ ! -f "$SIM_FILELIST" ]]; then
	echo "bootstrap_power_analysis: simulation TB filelist not found: $SIM_FILELIST" >&2
	echo "  Run simulation stage first; see skills/simulation/SKILL.md." >&2
	exit 1
fi

SYN_OUT_REL="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$SYN_OUT_DIR" "$DEST")"
SIM_REL="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$SIM_DIR" "$DEST")"
PLAN_REL="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$PLAN_DIR" "$DEST")"

# Substitute MY_TOP / MY_MODULE / MY_SYN_OUT / MY_SIM_DIR / MY_PLAN_DIR in env.sh.
# Use '|' as sed delimiter since path values contain '/'.
sed -i "s|MY_TOP|$TOP|g; s|MY_MODULE|$MODULE|g; \
        s|MY_SYN_OUT|$SYN_OUT_REL|g; s|MY_SIM_DIR|$SIM_REL|g; s|MY_PLAN_DIR|$PLAN_REL|g" \
	"$DEST/env.sh"

PLAN_PATH="$REPO_ROOT/asic/$MODULE/Verification/simulation-plan/scaffold-specification.json"
if [[ ! -f "$PLAN_PATH" ]]; then
	echo "bootstrap_power_analysis: simulation-plan not found: $PLAN_PATH" >&2
	exit 1
fi

python3 "$DEST/scripts/emit_power_tests.py" \
	--plan "$PLAN_PATH" \
	--module "$MODULE" \
	--out-dir "$DEST/scaffold/power_tests" \
	--filelist "$DEST/scaffold/power_filelist.f" \
	--top "$TOP" \
	--test-tmpl "$DEST/scaffold/power_test.sv.tmpl"

echo "bootstrap_power_analysis: Deployed $DEST with TOP=$TOP"
