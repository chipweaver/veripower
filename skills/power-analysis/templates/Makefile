# ==============================================================================
# IPD power-analysis — merged GLS power simulation + PT-PX averaged analysis.
#
# Workdir:           asic/<module>/Verification/power-analysis/
# External inputs:   Design/synthesis/out/<TOP>_syn.{v,sdc,sdf} + LIB_V + LIB_DB + UVM_HOME
#                    Verification/simulation/{filelist.f, tb/uvm/} (read-only TB infra)
#                    Verification/simulation-plan/scaffold-specification.json (power_scenarios[])
# Outputs:           simv (GLS) + saif/<id>.saif
#                    reports_ptpx/<id>/{power_hier,power_flat,switching_activity}.rpt
# ==============================================================================

ROOT := $(abspath .)
export ROOT

.PHONY: help all refresh-tests tb-shim gls-compile gls-run ptpx clean

help:  ## Show this help message
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

all: gls-compile gls-run ptpx  ## Run full power-analysis pipeline (GLS + PT-PX)

# Absolutize simulation/filelist.f against simulation TB dir so VCS can be
# invoked from this stage's workdir (runs/N/) without cd-ing.
tb-shim:  ## Absolutize simulation/filelist.f for VCS invocation from this workdir
	@bash -c 'set -eo pipefail; cd "$(ROOT)"; source ./env.sh; \
		python3 scripts/build_tb_filelist_abs.py \
			--tb-dir "$$TB_DIR" --out "$$TB_FILELIST_ABS"'

# Re-render UVM power test classes + power_filelist.f from the current plan.
# Idempotent — overwrites any previously-rendered classes. Runs before every
# gls-compile so plan changes (new scenario_id / new sequence_ref) propagate
# without needing a re-bootstrap.
refresh-tests:  ## Re-render UVM power test classes from current plan
	@bash -c 'set -eo pipefail; cd "$(ROOT)"; source ./env.sh; \
		[ -f "$$PLAN_PATH" ] || { echo "[refresh-tests] ERROR: PLAN_PATH not found: $$PLAN_PATH"; exit 1; }; \
		python3 scripts/emit_power_tests.py \
			--plan      "$$PLAN_PATH" \
			--module    "$$MODULE" \
			--out-dir   "$$POWER_TESTS_DIR" \
			--filelist  "$$POWER_FILELIST" \
			--top       "$$TOP" \
			--test-tmpl scaffold/power_test.sv.tmpl'

gls-compile: tb-shim refresh-tests  ## Compile GLS simv (synthesis netlist + SDF + TB)
	@bash -c 'set -eo pipefail; cd "$(ROOT)"; source ./env.sh; \
		[ -f "$$NETLIST" ]         || { echo "[gls-compile] ERROR: NETLIST not found: $$NETLIST"; exit 1; }; \
		[ -f "$$SDF_FILE" ]        || { echo "[gls-compile] ERROR: SDF_FILE not found: $$SDF_FILE"; exit 1; }; \
		[ -f "$$TB_FILELIST_ABS" ] || { echo "[gls-compile] ERROR: TB_FILELIST_ABS missing: $$TB_FILELIST_ABS (tb-shim should have created it)"; exit 1; }; \
		[ -f "$$POWER_FILELIST" ]  || { echo "[gls-compile] ERROR: POWER_FILELIST not found: $$POWER_FILELIST (refresh-tests should have created it)"; exit 1; }; \
		[ -f "$$LIB_V" ]           || { echo "[gls-compile] ERROR: LIB_V invalid: $${LIB_V:-<not set>}"; exit 1; }; \
		vcs -full64 -sverilog \
			-debug_access+all \
			-f "$$TB_FILELIST_ABS" \
			-f "$$POWER_FILELIST" \
			"$$NETLIST" "$$LIB_V" \
			-sdf max:$$VCS_SDF_SCOPE:$$SDF_FILE \
			$$VCS_TIMESCALE $$VCS_INIT_FLAGS \
			$${VCS_CC:+-cc "$$VCS_CC"} $${VCS_CPP:+-cpp "$$VCS_CPP"} \
			-LDFLAGS "-Wl,--no-as-needed -Wl,--allow-shlib-undefined" \
			-CFLAGS -DVCS +vpi "$$UVM_HOME/src/dpi/uvm_dpi.cc" \
			-o simv \
			2>&1 | tee gls-compile-log.txt; \
		bash scripts/check_sdf_annotated.sh gls-compile-log.txt'

gls-run: gls-compile  ## Run simv per scenario → per-scenario SAIF files
	@bash -c 'set -eo pipefail; cd "$(ROOT)"; source ./env.sh; \
		[ -x ./simv ] || { echo "[gls-run] ERROR: ./simv not built (gls-compile failed?)"; exit 1; }; \
		bash scripts/run_gls_power.sh \
			--plan "$$PLAN_PATH" \
			--saif-dir saif/ \
			--simv ./simv \
			--log gls-run-log.txt'

ptpx:  ## Run PT-PX averaged power analysis on SAIF batch
	@bash -c 'set -eo pipefail; cd "$(ROOT)"; source ./env.sh; \
		[ -f "$$LIB_DB" ] || { echo "[ptpx] ERROR: LIB_DB invalid: $${LIB_DB:-<not set>}"; exit 1; }; \
		[ -f "$$NETLIST" ] || { echo "[ptpx] ERROR: NETLIST missing: $$NETLIST"; exit 1; }; \
		[ -f "$$SDC_FILE" ] || { echo "[ptpx] ERROR: SDC_FILE missing: $$SDC_FILE"; exit 1; }; \
		[ -f "$$SDF_FILE" ] || { echo "[ptpx] ERROR: SDF_FILE missing: $$SDF_FILE"; exit 1; }; \
		\
		SAIF_LIST=$$(for f in saif/*.saif; do [ -f "$$f" ] || continue; id=$$(basename "$$f" .saif); echo "$$id=$$(realpath "$$f")"; done | tr "\n" " "); \
		[ -n "$$SAIF_LIST" ] || { echo "[ptpx] ERROR: no SAIF files in saif/"; exit 1; }; \
		echo "[ptpx] SAIF list: $$SAIF_LIST"; \
		\
		export NETLIST=$$(realpath "$$NETLIST") SDC_FILE=$$(realpath "$$SDC_FILE") SDF_FILE=$$(realpath "$$SDF_FILE") SAIF_LIST STRIP_PATH; \
		pt_shell -f scripts/ptpx.tcl 2>&1 | tee ptpx.log'

clean:  ## Remove intermediate artifacts and reports
	rm -rf simv simv.daidir saif/ scaffold/power_tests/ \
		scaffold/power_filelist.f tb_filelist_abs.f reports_ptpx/ \
		gls-compile-log.txt gls-run-log.txt ptpx.log \
		csrc/ ucli.key \
		command.log default.svf *.pvl *.svf svf.txt 2>/dev/null || true
