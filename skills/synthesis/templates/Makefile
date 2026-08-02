# ==============================================================================
# IPD synthesis — Design Compiler synthesis.
# Workdir:      synthesis stage per-run workdir
#               (<module>/Design/synthesis/runs/<N>/)
# RTL paths:    the absolute rtl-design stage root, written by synthesis bootstrap
#               into scripts/rtl_load.tcl + dc_run.tcl
# Top module:   synthesis bootstrap substitutes MY_TOP at deploy time.
# Targets:
#   make synthesis  run dc_shell synthesis; log → run.log
#   make clean      remove intermediate artifacts and reports
# Power analysis lives in a separate stage; see skills/power-analysis/.
# ==============================================================================

ROOT := $(abspath .)
export ROOT

.PHONY: help synthesis clean

help:  ## Show this help message
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

synthesis:  ## Run Design Compiler synthesis → run.log + out/ + reports/
	@mkdir -p out reports work
	@bash -c 'set -eo pipefail; cd "$(ROOT)"; source ./env.sh; export TOP LIB_DB; \
		dc_shell -f scripts/dc_run.tcl 2>&1 | tee run.log'

clean:  ## Remove intermediate artifacts and reports
	rm -rf out reports work
	rm -f run.log command.log default.svf *.pvl *.svf svf.txt 2>/dev/null || true
