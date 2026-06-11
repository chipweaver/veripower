#!/usr/bin/env bash
# Deploy simulation skill infrastructure into the simulation stage's per-run
# workdir (asic/<module>/Verification/simulation/runs/<N>/, provided by the
# caller) and optionally generate UVM scaffold from scaffold-spec.json.
# Invoked by the agent under veripower:simulation; may also be run manually.
set -euo pipefail

usage() {
	echo "Usage: $0 --module <module-dir-name> --workdir <abs-path> [--top <top-module>] [--plan <scaffold-spec.json>]" >&2
	echo "" >&2
	echo "  --workdir  simulation stage per-run workdir absolute path (caller-provided)." >&2
	echo "             Shape: asic/<M>/Verification/simulation/runs/<N>/." >&2
	echo "             Templates and scaffold output land in this directory;" >&2
	echo "             env.sh / rtl_filelist.f relative paths are computed from" >&2
	echo "             workdir depth (no hardcoded ../Design/...)." >&2
	echo "  --plan     Approved verification scaffold-spec JSON." >&2
	echo "             When provided, bootstrap generates the full UVM scaffold." >&2
	echo "             When omitted, only infra is deployed (Makefile/env.sh/scripts/" >&2
	echo "             base_test/base_seq)." >&2
	exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="${SCRIPT_DIR}/../templates"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

MODULE=""
TOP=""
PLAN=""
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
	--plan)
		shift
		[[ $# -gt 0 ]] || usage
		PLAN="$1"
		shift
		;;
	--workdir)
		shift
		[[ $# -gt 0 ]] || usage
		WORKDIR="$1"
		shift
		;;
	-h | --help)
		usage
		;;
	*)
		echo "unknown flag: $1" >&2
		usage
		;;
	esac
done

[[ -n "$MODULE" ]] || usage
[[ -n "$WORKDIR" ]] || {
	echo "bootstrap_simulation: --workdir <path> is required" >&2
	usage
}
[[ -d "$TEMPLATE_DIR/infra" ]] || {
	echo "bootstrap_simulation: missing infra template directory: $TEMPLATE_DIR/infra" >&2
	exit 1
}

# Resolve WORKDIR to absolute path (allow caller to pass relative).
if [[ "$WORKDIR" != /* ]]; then
	WORKDIR="$REPO_ROOT/$WORKDIR"
fi
# Strip trailing slash so relpath math is consistent.
WORKDIR="${WORKDIR%/}"

RTL_DIR="$REPO_ROOT/asic/$MODULE/Design/rtl-design"
SPEC_DIR="$REPO_ROOT/asic/$MODULE/Design/specification"
DEST="$WORKDIR"
RTL_FILELIST="$RTL_DIR/filelist.txt"

# Compute relpath(target, DEST) so env.sh / rtl_filelist.f stay portable
# regardless of workdir depth (runs/<N>/ vs canonical Verification/simulation/).
RTL_REL_DIR="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$RTL_DIR" "$DEST")"
SPEC_REL_DIR="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$SPEC_DIR" "$DEST")"

# --- Infer TOP from README or filelist ---
infer_top_from_readme() {
	local f="$RTL_DIR/README.md"
	[[ -f "$f" ]] || return 0
	local line
	line=$(grep -iE '(^|[*#[:space:]])(top|top[[:space:]]+module)' "$f" 2>/dev/null | grep -Ev '^[[:space:]]*\|' | head -1 || true)
	[[ -n "$line" ]] || return 0
	local top
	top=$(echo "$line" | sed -E 's/^[^:：]*[:：][[:space:]]*([A-Za-z0-9_]+).*$/\1/' | tr -d '\r')
	[[ "$top" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 0
	echo "$top"
}

infer_top_from_filelist() {
	local f="$RTL_DIR/filelist.txt"
	[[ -f "$f" ]] || return 0
	local first
	# Skip comments, blank lines, and +/- directives (+incdir+ / -f / +define+);
	# keep only true RTL path entries.
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
	# Reject non-identifier basenames so we don't treat "+incdir+include" /
	# path fragments as a top-module name.
	[[ "$base" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 0
	echo "$base"
}

if [[ -z "${TOP:-}" ]]; then TOP="$(infer_top_from_readme)"; fi
if [[ -z "${TOP:-}" ]]; then TOP="$(infer_top_from_filelist)"; fi
if [[ -z "${TOP:-}" ]]; then
	echo "bootstrap_simulation: cannot infer top-module name; pass --top <name>" >&2
	exit 1
fi

# --- Prerequisite checks ---
[[ -f "$RTL_FILELIST" ]] || {
	echo "bootstrap_simulation: missing RTL filelist: $RTL_FILELIST" >&2
	exit 1
}

# --- Prevent overwrite (only block if infra already deployed) ---
# The caller may pre-create the workdir with hint files (orchestrator-context.md
# etc.); only treat the directory as "already deployed" when Makefile exists.
mkdir -p "$DEST"
if [[ -f "$DEST/Makefile" ]]; then
	echo "bootstrap_simulation: infra already deployed (detected $DEST/Makefile)" >&2
	echo "  To re-render the scaffold, remove Makefile or invoke derive_scaffold.py directly." >&2
	exit 1
fi

# ==========================================================================
# Step 1: Deploy infra layer (Makefile, env.sh, scripts, base_test, base_seq)
# ==========================================================================
echo "bootstrap_simulation: deploying infra..."
cp -a "$TEMPLATE_DIR/infra/." "$DEST"

# Create UVM subdirectories for scaffold output
for d in interface transaction agent checker refmodel env seq test pkg top; do
	mkdir -p "$DEST/tb/uvm/$d"
done
mkdir -p "$DEST/tests"

# Replace MY_MODULE / MY_TOP / MY_RTL_DIR / MY_SPEC_DIR in infra files.
# RTL_REL_DIR / SPEC_REL_DIR may contain '..' segments; use '|' as sed
# delimiter so '/' inside the value is harmless.
while IFS= read -r path; do
	sed -i "s#MY_TOP#${TOP}#g; s#MY_MODULE#${MODULE}#g" "$path"
	sed -i "s|MY_RTL_DIR|${RTL_REL_DIR}|g; s|MY_SPEC_DIR|${SPEC_REL_DIR}|g" "$path"
done < <(
	if command -v rg >/dev/null 2>&1; then
		rg -l 'MY_TOP|MY_MODULE|MY_RTL_DIR|MY_SPEC_DIR' "$DEST" || true
	else
		grep -rl 'MY_TOP\|MY_MODULE\|MY_RTL_DIR\|MY_SPEC_DIR' "$DEST" 2>/dev/null || true
	fi
)

chmod +x "$DEST/scripts"/*.sh 2>/dev/null || true

# ==========================================================================
# Step 2: Generate rtl_filelist.f from Design/rtl-design/filelist.txt
# ==========================================================================
echo "bootstrap_simulation: generating rtl_filelist.f..."
python3 "$SCRIPT_DIR/build_rtl_filelist.py" \
	--src "$RTL_FILELIST" \
	--dst "$DEST/rtl_filelist.f" \
	--rtl-rel "$RTL_REL_DIR"

# ==========================================================================
# Step 3: Generate scaffold from plan (if --plan provided)
# ==========================================================================
if [[ -n "$PLAN" ]]; then
	PLAN_PATH="$PLAN"
	# Resolve relative path
	if [[ ! "$PLAN_PATH" = /* ]]; then
		PLAN_PATH="$REPO_ROOT/$PLAN_PATH"
	fi
	[[ -f "$PLAN_PATH" ]] || {
		echo "bootstrap_simulation: missing scaffold-spec.json: $PLAN_PATH" >&2
		exit 1
	}
	echo "bootstrap_simulation: rendering UVM scaffold from plan..."
	python3 "$SCRIPT_DIR/derive_scaffold.py" \
		--plan "$PLAN_PATH" \
		--template-dir "$TEMPLATE_DIR/scaffold" \
		--output-dir "$DEST"
else
	echo "bootstrap_simulation: --plan not supplied; deployed infra only."
	echo "  Next steps:"
	echo "  1. Prepare verification-plan.md and scaffold-specification.json (under Verification/simulation-plan/)."
	echo "  2. Run derive_scaffold.py --plan <path> --output-dir $DEST"
fi

echo ""
echo "bootstrap_simulation: done — $DEST"
echo "  MODULE=$MODULE  TOP=$TOP"
