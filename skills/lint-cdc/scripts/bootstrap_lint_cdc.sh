#!/usr/bin/env bash
# Deploy lint-cdc skill templates into the lint-cdc stage's per-run workdir
# (typically asic/<module>/Design/lint-cdc/runs/<N>/, provided by the caller),
# and substitute the TOP placeholder (MY_TOP).
# If Design/rtl-design/filelist.txt exists, its contents are synced into
# scripts/filelist.txt. RTL paths in filelist.txt are written as
# ../../../rtl-design/... (relative to scripts/filelist.txt:
# scripts/ → runs/<N>/ → lint-cdc/ → Design/ → rtl-design/).
#
# Usage:
#   bash ${CLAUDE_SKILL_DIR}/scripts/bootstrap_lint_cdc.sh \
#        --module <module-dir-name> --workdir <abs-path> [--top <top-module>]
#
# When --top is omitted: inferred from <module>/Design/rtl-design/README.md
# (lines containing a `top` keyword) or the first line of filelist.txt.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="${SCRIPT_DIR}/../templates"

usage() {
	echo "Usage: $0 --module <module-dir-name> --workdir <abs-path> [--top <top-module>]" >&2
	echo "" >&2
	echo "  --workdir  lint-cdc stage per-run workdir absolute path (caller-provided)." >&2
	echo "             Shape: asic/<M>/Design/lint-cdc/runs/<N>/." >&2
	echo "  --top      Top module name; inferred from Design/rtl-design/README.md or" >&2
	echo "             the first line of filelist.txt when omitted." >&2
	echo "  Template source: ${TEMPLATE_DIR}" >&2
	exit 2
}

REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TEMPLATE="$TEMPLATE_DIR"

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
	echo "bootstrap_lint_cdc: --workdir <path> is required" >&2
	usage
}
[[ -d "$TEMPLATE" ]] || {
	echo "bootstrap_lint_cdc: missing template directory: $TEMPLATE" >&2
	exit 1
}

# Resolve WORKDIR to absolute path (allow caller to pass relative).
if [[ "$WORKDIR" != /* ]]; then
	WORKDIR="$REPO_ROOT/$WORKDIR"
fi
# Strip trailing slash for consistent path math.
WORKDIR="${WORKDIR%/}"

RTL_DIR="$REPO_ROOT/asic/$MODULE/Design/rtl-design"
DEST="$WORKDIR"

infer_top_from_readme() {
	local f="$RTL_DIR/README.md"
	[[ -f "$f" ]] || return 0
	# Match "Top: foo" / "top module: foo" etc.; skip table rows.
	local line
	line=$(grep -iE '(^|[*#[:space:]])(top|top[[:space:]]+module)' "$f" 2>/dev/null | grep -Ev '^[[:space:]]*\|' | head -1 || true)
	if [[ -z "$line" ]]; then
		return 0
	fi
	local top
	top=$(echo "$line" | sed -E 's/^[^:]*:[[:space:]]*([A-Za-z0-9_]+).*$/\1/' | tr -d '\r')
	if [[ ! "$top" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
		return 0
	fi
	echo "$top"
}

infer_top_from_filelist() {
	local f="$RTL_DIR/filelist.txt"
	[[ -f "$f" ]] || return 0
	local first
	# Skip comments, blank lines, and +/- directives (+incdir+ / -f / +define+);
	# keep only RTL paths.
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
	# Reject non-identifier basenames so we don't treat path fragments as a top name.
	[[ "$base" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 0
	echo "$base"
}

if [[ -z "${TOP:-}" ]]; then
	TOP="$(infer_top_from_readme)"
fi
if [[ -z "${TOP:-}" ]]; then
	TOP="$(infer_top_from_filelist)"
fi
if [[ -z "${TOP:-}" ]]; then
	echo "bootstrap_lint_cdc: cannot infer top-module name; pass --top <name>" >&2
	echo "  Either add a 'Top: <name>' line to Design/rtl-design/README.md, or" >&2
	echo "  ensure Design/rtl-design/filelist.txt begins with an RTL path." >&2
	exit 1
fi

mkdir -p "$DEST"
# The caller may pre-create the workdir with hint files (orchestrator-context.md
# etc.); only treat the directory as "already deployed" when Makefile exists.
if [[ -f "$DEST/Makefile" ]]; then
	echo "bootstrap_lint_cdc: already deployed (detected $DEST/Makefile)" >&2
	echo "  To redeploy, back up and remove $DEST/{Makefile,env.sh,scripts/} first." >&2
	exit 1
fi

cp -a "$TEMPLATE/." "$DEST"

# SGDC seed: warm → cold → template priority (warm = lint-cdc canonical, cold =
# spec <TOP>.sgdc, else the in-tree template). Authoritative description:
# references/makefile-bootstrap.md "SGDC source selection".
SGDC_SOURCE=""
WARM_SGDC="$REPO_ROOT/asic/$MODULE/Design/lint-cdc/scripts/constraints.sgdc"
COLD_SGDC="$REPO_ROOT/asic/$MODULE/Design/specification/constraints/${TOP}.sgdc"
if [[ -f "$WARM_SGDC" ]]; then
	cp -f "$WARM_SGDC" "$DEST/scripts/constraints.sgdc"
	echo "bootstrap_lint_cdc: warm-start used Design/lint-cdc/scripts/constraints.sgdc → lint-cdc/scripts/constraints.sgdc"
	SGDC_SOURCE="Design/lint-cdc/scripts/constraints.sgdc (warm)"
	# Warm SGDC is already bound to a concrete top; do not re-substitute MY_TOP.
	sed -i "s#MY_TOP#${TOP}#g" \
		"$DEST/env.sh" \
		"$DEST/scripts/spyglass_lint.prj" \
		"$DEST/scripts/filelist.txt" \
		"$DEST/scripts/waiver.tcl"
elif [[ -f "$COLD_SGDC" ]]; then
	cp -f "$COLD_SGDC" "$DEST/scripts/constraints.sgdc"
	echo "bootstrap_lint_cdc: cold-start used Design/specification/constraints/${TOP}.sgdc → lint-cdc/scripts/constraints.sgdc"
	SGDC_SOURCE="Design/specification/constraints/${TOP}.sgdc (cold)"
	# Cold SGDC is already bound to a concrete top; do not re-substitute MY_TOP.
	sed -i "s#MY_TOP#${TOP}#g" \
		"$DEST/env.sh" \
		"$DEST/scripts/spyglass_lint.prj" \
		"$DEST/scripts/filelist.txt" \
		"$DEST/scripts/waiver.tcl"
else
	# No seed source: substitute MY_TOP into every placeholder-bearing template.
	sed -i "s#MY_TOP#${TOP}#g" \
		"$DEST/env.sh" \
		"$DEST/scripts/spyglass_lint.prj" \
		"$DEST/scripts/filelist.txt" \
		"$DEST/scripts/constraints.sgdc" \
		"$DEST/scripts/waiver.tcl"
fi

chmod +x "$DEST/scripts"/*.sh 2>/dev/null || true

# If Design/rtl-design/filelist.txt exists, sync its contents into
# scripts/filelist.txt, replacing the single-file placeholder while preserving
# the header comments and the +incdir+ line.
write_filelist_txt() {
	local fl="$RTL_DIR/filelist.txt"
	[[ -f "$fl" ]] || return 0

	# Scan once to count RTL entries; empty filelist is fail-closed (avoids
	# silently producing a stub that points to ${TOP}.v when the real top is .sv).
	local count=0
	while IFS= read -r line || [[ -n "$line" ]]; do
		[[ "$line" =~ ^[[:space:]]*# ]] && continue
		[[ -z "${line//[[:space:]]/}" ]] && continue
		count=$((count + 1))
	done <"$fl"

	if [[ "$count" -eq 0 ]]; then
		echo "bootstrap_lint_cdc: $fl has no usable RTL entries (only comments / blank lines)" >&2
		echo "  Populate Design/rtl-design/filelist.txt with .v / .sv paths in dependency order." >&2
		exit 1
	fi

	local out="$DEST/scripts/filelist.txt"
	{
		echo "# =============================================================================="
		echo "# filelist.txt — RTL file list (SpyGlass sourcelist format)."
		echo "# Generated by bootstrap_lint_cdc.sh from Design/rtl-design/filelist.txt."
		echo "# Paths are relative to Design/lint-cdc/runs/<N>/ (the deployment location)."
		echo "# =============================================================================="
		echo ""
		echo "# Header search paths"
		echo "+incdir+../../../rtl-design"
		echo ""
		echo "# RTL source files (in dependency order)"
		while IFS= read -r line || [[ -n "$line" ]]; do
			[[ "$line" =~ ^[[:space:]]*# ]] && continue
			[[ -z "${line//[[:space:]]/}" ]] && continue
			line=$(echo "$line" | tr -d '\r')
			echo "../../../rtl-design/$line"
		done <"$fl"
	} >"$out"

	echo "  filelist.txt: synced from Design/rtl-design/filelist.txt (${count} files)"
}

write_filelist_txt

# Cross-check the first clock period in Design/specification/constraints/<TOP>.sgdc
# vs <TOP>.sdc. Multi-clock designs only compare the first definition in each
# file as a smoke test; precise alignment is enforced by design.md §1.6.
check_sgdc_sdc_period() {
	local sgdc="$REPO_ROOT/asic/$MODULE/Design/specification/constraints/${TOP}.sgdc"
	local sdc="$REPO_ROOT/asic/$MODULE/Design/specification/constraints/${TOP}.sdc"
	[[ -f "$sgdc" && -f "$sdc" ]] || return 0

	local sgdc_period sdc_period
	sgdc_period=$(grep -E '^\s*clock\s' "$sgdc" 2>/dev/null |
		grep -oE '\-period[[:space:]]+[0-9]+(\.[0-9]+)?' | head -1 |
		grep -oE '[0-9]+(\.[0-9]+)?' || true)
	sdc_period=$(grep -E '^\s*create_clock\s' "$sdc" 2>/dev/null |
		grep -oE '\-period[[:space:]]+[0-9]+(\.[0-9]+)?' | head -1 |
		grep -oE '[0-9]+(\.[0-9]+)?' || true)

	[[ -n "$sgdc_period" && -n "$sdc_period" ]] || return 0
	if [[ "$sgdc_period" != "$sdc_period" ]]; then
		echo "WARNING: bootstrap_lint_cdc: SGDC and SDC clock periods disagree; update per design.md §1.6 before re-running." >&2
		echo "  ${TOP}.sgdc  clock -period       = ${sgdc_period} ns" >&2
		echo "  ${TOP}.sdc   create_clock -period = ${sdc_period} ns" >&2
	fi
}

check_sgdc_sdc_period

echo "bootstrap_lint_cdc: deployed $DEST"
echo "  TOP=$TOP"
if [[ -n "$SGDC_SOURCE" ]]; then
	echo "  clock/reset constraints: synced from $SGDC_SOURCE; add abstract_port associations as needed."
else
	echo "  clock/reset constraints: edit scripts/constraints.sgdc (clock / reset / abstract_port)."
fi
echo "  Next: cd \"$DEST\" && make all   (requires SpyGlass; -shell -tcl mode does not need Xvfb)"
