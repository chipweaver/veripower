# ==============================================================================
# Bare EDA tool wrapper — flat, no cross-stage orchestration.
# Each target invokes one tool with manual-level flags. YOU decide when to run
# what, how to iterate, how to self-check. Provide your own RTL/TB/constraints/
# filelist (see README.md). Nothing here is VeriPower- or design-specific.
#   make lint | cdc | synth | sta | sim-compile | sim-run TEST=<name> | coverage
# ==============================================================================
SHELL := /bin/bash
FILELIST ?= filelist.f
SIMV ?= ./simv

.PHONY: help lint cdc synth sta sim-compile sim-run coverage merge clean

help:  ## Show targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

lint:  ## SpyGlass lint
	@source ./env.sh && SPYGLASS_STAGE=lint spyglass -64bit -shell -tcl scripts/run_spyglass.tcl

cdc:  ## SpyGlass CDC
	@source ./env.sh && SPYGLASS_STAGE=cdc spyglass -64bit -shell -tcl scripts/run_spyglass.tcl

synth:  ## Design Compiler synthesis → out/ + reports/
	@source ./env.sh && dc_shell -f scripts/dc_run.tcl 2>&1 | tee run.log

sta:  ## PrimeTime STA on out/<TOP>_syn.v → timing-report.txt
	@source ./env.sh && pt_shell -f scripts/run_sta.tcl 2>&1 | tee sta.log

sim-compile:  ## VCS compile a UVM testbench → ./simv
	@source ./env.sh && vcs -full64 -f $(FILELIST) -sverilog -debug_access+all \
		-kdb -lca $$VCS_COV -timescale=1ns/1ps \
		-LDFLAGS "-Wl,--no-as-needed -Wl,--allow-shlib-undefined" \
		-CFLAGS -DVCS +vpi "$$UVM_HOME/src/dpi/uvm_dpi.cc" -o simv 2>&1 | tee com.log

sim-run:  ## Run one UVM test: make sim-run TEST=<uvm_testname>
	@source ./env.sh && [ -x "$(SIMV)" ] || { echo "no ./simv — run 'make sim-compile' first"; exit 1; }
	@source ./env.sh && $(SIMV) +UVM_TESTNAME=$(TEST) $$VCS_COV -cm_dir cov_test -l sim.log

coverage:  ## Merge coverage to a text report (urg)
	@source ./env.sh && urg -dir simv.vdb -dir cov_test.vdb -report cov_merge -format text

merge:  ## Merge coverage dbs (urg)
	@source ./env.sh && urg -dir simv.vdb -dir cov_test.vdb -report both -dbname both.vdb

clean:  ## Remove build artifacts
	rm -rf out reports work spyglass_work simv simv.daidir csrc cov_test* *.vdb cov_merge
	rm -f run.log sta.log com.log sim.log timing-report.txt command.log *.svf ucli.key vc_hdrs.h
