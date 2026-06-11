#!/usr/bin/env bash
# Deploy the synthesis skill templates into the synthesis stage's per-run workdir
# (asic/<module>/Design/synthesis/runs/<N>/, provided by the caller), substitute
# the TOP placeholder, and generate rtl_load.tcl.
# Invoked by the agent under veripower:synthesis; may also be run manually.
#
# Usage:
#   bash ${CLAUDE_SKILL_DIR}/scripts/bootstrap_synthesis.sh \
#        --module <module-dir-name> --workdir <abs-path> [--top <top-module>]
#
# When --top is omitted: inferred from <module>/Design/rtl-design/README.md
# (the "Top" line) or the first RTL path in filelist.txt.
set -euo pipefail

usage() {
	echo "Usage: $0 --module <module-dir-name> --workdir <abs-path> [--top <top-module>]" >&2
	echo "" >&2
	echo "  --workdir  synthesis stage per-run workdir absolute path (caller-provided)." >&2
	echo "             Shape: asic/<M>/Design/synthesis/runs/<N>/." >&2
	echo "             Templates, rtl_load.tcl, and config.tcl land in this directory;" >&2
	echo "             dc_run.tcl's RTL search_path is computed from workdir depth" >&2
	echo "             (no hardcoded ../rtl-design)." >&2
	echo "  --top      Top module name; inferred from Design/rtl-design/README.md or" >&2
	echo "             the first RTL path in filelist.txt when omitted." >&2
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
	echo "bootstrap_synthesis: --workdir <path> is required" >&2
	usage
}
[[ -d "$TEMPLATE_DIR" ]] || {
	echo "bootstrap_synthesis: missing template directory: $TEMPLATE_DIR" >&2
	exit 1
}

# Resolve WORKDIR to absolute path (allow caller to pass relative).
if [[ "$WORKDIR" != /* ]]; then
	WORKDIR="$REPO_ROOT/$WORKDIR"
fi
# Strip trailing slash so relpath math is consistent.
WORKDIR="${WORKDIR%/}"

RTL_DIR="$REPO_ROOT/asic/$MODULE/Design/rtl-design"
DEST="$WORKDIR"

# Compute relpath(RTL_DIR, DEST) so dc_run.tcl + rtl_load.tcl stay portable
# regardless of workdir depth (runs/<N>/ vs canonical Design/synthesis/).
RTL_REL_DIR="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$RTL_DIR" "$DEST")"

infer_top_from_readme() {
	local f="$RTL_DIR/README.md"
	[[ -f "$f" ]] || return 0
	local line
	# Exclude Markdown table rows (| ... |) so a "top" cell inside a table doesn't match.
	line=$(grep -iE '(^|[*#[:space:]])(top|top[[:space:]]+module)' "$f" 2>/dev/null | grep -Ev '^[[:space:]]*\|' | head -1 || true)
	if [[ -z "$line" ]]; then
		return 0
	fi
	local top
	top=$(echo "$line" | sed -E 's/^[^:：]*[:：][[:space:]]*([A-Za-z0-9_]+).*$/\1/' | tr -d '\r')
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
	# Mirror infer_top_from_readme: reject non-identifier basenames so we don't
	# treat e.g. "+incdir+include" as a top-module name when filelist.txt is
	# malformed past the +/- filter above.
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
	echo "bootstrap_synthesis: cannot infer top-module name; pass --top <name>" >&2
	echo "  Either add a 'Top: <name>' line to Design/rtl-design/README.md, or" >&2
	echo "  ensure Design/rtl-design/filelist.txt begins with an RTL path." >&2
	exit 1
fi

mkdir -p "$DEST"
# The caller may pre-create the workdir with hint files (orchestrator-context.md
# etc.); only treat the directory as "already deployed" when Makefile exists.
if [[ -f "$DEST/Makefile" ]]; then
	echo "bootstrap_synthesis: already deployed (detected $DEST/Makefile)" >&2
	echo "  To redeploy, back up and remove $DEST/{Makefile,constraints.sdc,scripts/} first." >&2
	exit 1
fi

cp -a "$TEMPLATE_DIR/." "$DEST"

# Optional: if specification stage produced an SDC for this top, reuse it
# verbatim (signals / timing already match the design, no template edit needed).
USER_SDC="$REPO_ROOT/asic/$MODULE/Design/specification/constraints/${TOP}.sdc"
if [[ -f "$USER_SDC" ]]; then
	cp -f "$USER_SDC" "$DEST/constraints.sdc"
	echo "bootstrap_synthesis: using Design/specification/constraints/${TOP}.sdc → constraints.sdc"
	sed -i "s#MY_TOP#${TOP}#g" "$DEST/env.sh"
else
	sed -i "s#MY_TOP#${TOP}#g" "$DEST/env.sh" "$DEST/constraints.sdc"
fi

# Substitute MY_RTL_DIR in dc_run.tcl. RTL_REL_DIR may contain '..' segments,
# so use '|' as the sed delimiter to avoid '/' collisions.
sed -i "s|MY_RTL_DIR|${RTL_REL_DIR}|g" "$DEST/scripts/dc_run.tcl"

# Generate rtl_load.tcl. We use `analyze -format sverilog -define SYNTHESIS`
# (rather than read_verilog) so RTL guarded by `ifdef SYNTHESIS is activated
# during synthesis. filelist.txt entries are written as paths relative to
# Design/rtl-design/; we prepend ${RTL_REL_DIR}/ verbatim (no prefix-stripping).
# +incdir+<dir> entries (emitted by rtl-design's build_filelist.py) are expanded
# onto search_path (RTL_REL_DIR-relative, same base as file entries) so `include
# of a file outside the RTL root resolves; +define+ / -f directives are skipped
# (-define SYNTHESIS is already passed per analyze; nested -f is out of scope).
# Empty / missing filelist is fail-closed to avoid silently producing a stub
# that points to ${TOP}.v when the real top is e.g. ${TOP}.sv.
write_rtl_load_tcl() {
	local out="$DEST/scripts/rtl_load.tcl"
	local fl="$RTL_DIR/filelist.txt"

	if [[ ! -f "$fl" ]]; then
		echo "bootstrap_synthesis: missing $fl" >&2
		echo "  Populate Design/rtl-design/filelist.txt with .v / .sv paths in dependency order." >&2
		exit 1
	fi

	# Scan to count RTL entries first; empty filelist is fail-closed.
	local count=0
	while IFS= read -r line || [[ -n "$line" ]]; do
		[[ "$line" =~ ^[[:space:]]*# ]] && continue
		[[ "$line" =~ ^[[:space:]]*//.* ]] && continue
		[[ -z "${line//[[:space:]]/}" ]] && continue
		[[ "$line" =~ ^[[:space:]]*[+\-] ]] && continue
		count=$((count + 1))
	done <"$fl"

	if [[ "$count" -eq 0 ]]; then
		echo "bootstrap_synthesis: $fl has no usable RTL entries (only comments / directives)" >&2
		echo "  Populate Design/rtl-design/filelist.txt with .v / .sv paths in dependency order." >&2
		exit 1
	fi

	# Collect +incdir+ directories (not RTL files, so they don't count above) and
	# rebase each by RTL_REL_DIR for the generated search_path line.
	local incdirs=()
	while IFS= read -r line || [[ -n "$line" ]]; do
		line=$(echo "$line" | tr -d '\r')
		if [[ "$line" =~ ^[[:space:]]*\+incdir\+(.+)$ ]]; then
			incdirs+=("${RTL_REL_DIR}/${BASH_REMATCH[1]}")
		fi
	done <"$fl"

	{
		echo "# Generated by bootstrap_synthesis.sh from Design/rtl-design/filelist.txt — hand-edit OK"
		if [[ ${#incdirs[@]} -gt 0 ]]; then
			echo "set_app_var search_path [concat [get_app_var search_path] [list ${incdirs[*]}]]"
		fi
		while IFS= read -r line || [[ -n "$line" ]]; do
			[[ "$line" =~ ^[[:space:]]*# ]] && continue
			[[ "$line" =~ ^[[:space:]]*//.* ]] && continue
			[[ -z "${line//[[:space:]]/}" ]] && continue
			# +incdir+ is handled above (search_path); +define+ / -f are intentionally
			# not expanded here.
			[[ "$line" =~ ^[[:space:]]*[+\-] ]] && continue
			line=$(echo "$line" | tr -d '\r')
			echo "analyze -format sverilog -define SYNTHESIS [list ${RTL_REL_DIR}/$line]"
		done <"$fl"
	} >"$out"
}

write_rtl_load_tcl

# Generate scripts/config.tcl. dc_shell / pt_shell do not inherit shell env
# vars, so this Tcl file is the canonical entry for TOP and LIB_DB.
# If $LIB_DB is already exported (project convention: in ~/.bashrc), bootstrap
# captures its value here; otherwise write the FILL_IN_LIB_DB_PATH placeholder
# for the user to fill before `make synthesis`.
LIB_DB_VALUE="${LIB_DB:-FILL_IN_LIB_DB_PATH}"
cat >"$DEST/scripts/config.tcl" <<TCLEOF
# Auto-generated by bootstrap_synthesis.sh — dc_shell / pt_shell configuration.
# dc_shell does not inherit shell env vars; this file is the sole entry point
# for TOP and LIB_DB. Editing LIB_DB here does not require a re-bootstrap.
set ::env(TOP)    "${TOP}"
set ::env(LIB_DB) "${LIB_DB_VALUE}"
TCLEOF
if [[ "$LIB_DB_VALUE" == "FILL_IN_LIB_DB_PATH" ]]; then
	echo "bootstrap_synthesis: wrote scripts/config.tcl (fill in LIB_DB path before make synthesis)"
else
	echo "bootstrap_synthesis: wrote scripts/config.tcl (LIB_DB=${LIB_DB_VALUE})"
fi

echo ""
echo "bootstrap_synthesis: deployed $DEST"
echo "  TOP=$TOP"
echo "  RTL_REL_DIR=$RTL_REL_DIR"
echo "  Next steps:"
echo "  1. Edit scripts/config.tcl to fill in LIB_DB (if not already set)."
echo "  2. Edit constraints.sdc if timing exceptions need to be added."
echo "  3. cd \"$DEST\" && make synthesis"
