#!/usr/bin/env bash
# ==============================================================================
# run_spyglass.sh — unified SpyGlass -shell -tcl launcher.
#
# The Makefile picks the goal subset via SPYGLASS_STAGE:
#   SPYGLASS_STAGE=lint  make lint
#   SPYGLASS_STAGE=cdc   make cdc
#   SPYGLASS_STAGE=all   make all (default)
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1
rm -f result.json
mkdir -p spyglass_work

# Setup must return before prior summaries can be reused. Preserve raw reports
# for inspection when setup aborts, including an explicit exit from env.sh.
trap 'rm -f lint-violations.json cdc-violations.json; exit 1' EXIT
set -a
# shellcheck disable=SC1091
[ -f env.sh ] && . ./env.sh
set +a
trap - EXIT

case "${SPYGLASS_STAGE:-all}" in
lint) rm -f lint-report.txt lint-violations.json ;;
cdc) rm -f cdc-report.txt cdc-violations.json ;;
all) rm -f lint-report.txt lint-violations.json cdc-report.txt cdc-violations.json ;;
esac

TCL_ENTRY="scripts/run.tcl"

if ! command -v spyglass >/dev/null 2>&1; then
	echo "[run_spyglass] ERROR: spyglass not found in PATH." >&2
	exit 1
fi

if [ ! -f "$TCL_ENTRY" ]; then
	echo "[run_spyglass] ERROR: TCL script not found: $TCL_ENTRY" >&2
	exit 1
fi

exec spyglass -64bit -shell -tcl "$TCL_ENTRY"
