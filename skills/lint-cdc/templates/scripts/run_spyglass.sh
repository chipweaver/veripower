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
mkdir -p spyglass_work

set -a
# shellcheck disable=SC1091
[ -f env.sh ] && . ./env.sh
set +a

TCL_ENTRY="scripts/run.tcl"
TIMEOUT_SEC="${SPYGLASS_TIMEOUT:-1800}"

if ! command -v spyglass >/dev/null 2>&1; then
	echo "[run_spyglass] ERROR: spyglass not found in PATH." >&2
	exit 1
fi

if [ ! -f "$TCL_ENTRY" ]; then
	echo "[run_spyglass] ERROR: TCL script not found: $TCL_ENTRY" >&2
	exit 1
fi

set +e
if command -v timeout >/dev/null 2>&1; then
	timeout "$TIMEOUT_SEC" spyglass -64bit -shell -tcl "$TCL_ENTRY"
else
	echo "[run_spyglass] WARNING: timeout(1) not available; SpyGlass will run untimed." >&2
	spyglass -64bit -shell -tcl "$TCL_ENTRY"
fi
R=$?
set -e

[ "$R" -eq 124 ] && echo "[run_spyglass] ERROR: SpyGlass timed out after ${TIMEOUT_SEC}s." >&2
exit "$R"
