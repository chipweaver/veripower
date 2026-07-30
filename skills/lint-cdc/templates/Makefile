# ==============================================================================
# IPD lint-cdc — SpyGlass lint + CDC checks.
# Workdir:    asic/<module>/Design/lint-cdc/runs/<N>/
# RTL path:   the absolute rtl-design stage root injected via dispatch.json's
#             "rtl" key; scripts/filelist.txt is regenerated from it every
#             round by the bootstrap verb's _sync_filelist (no relpath climb).
# Top module: the lint-cdc bootstrap verb substitutes MY_TOP at deploy time.
# Targets:
#   make lint         lint/lint_rtl goal only → lint-report.txt
#   make cdc          CDC three-stage goal only → cdc-report.txt
#   make all          lint + CDC single session → both reports (recommended)
#   make lint-report  aggregate existing SpyGlass output → lint-report.txt
#   make cdc-report   aggregate existing SpyGlass output → cdc-report.txt
#   make clean        remove intermediate artifacts and reports
# ==============================================================================

ROOT := $(abspath .)
export ROOT

.PHONY: help mkdirs lint cdc lint-report cdc-report all clean

help:  ## Show this help message
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

all: mkdirs  ## lint + CDC single session (recommended for first run)
	@echo "[lint-cdc] Running SpyGlass lint + CDC (single session)..."
	@chmod +x scripts/run_spyglass.sh
	@SPYGLASS_STAGE=all ./scripts/run_spyglass.sh
	@$(MAKE) --no-print-directory lint-report cdc-report
	@echo "[lint-cdc] Done. Reports: lint-report.txt, cdc-report.txt"

mkdirs:
	@mkdir -p spyglass_work

lint: mkdirs  ## Run lint goal only → lint-report.txt
	@echo "[lint-cdc] Running SpyGlass lint/lint_rtl..."
	@chmod +x scripts/run_spyglass.sh
	@SPYGLASS_STAGE=lint ./scripts/run_spyglass.sh
	@$(MAKE) --no-print-directory lint-report
	@echo "[lint-cdc] Done. Report: lint-report.txt"

# Recommended first run: `make all` shares the elaborate cache between lint
# and CDC. `make cdc` is also valid (CDC goals each elaborate themselves), but
# only after SGDC has stabilized.
cdc: mkdirs  ## Run CDC three-stage goal only → cdc-report.txt
	@echo "[lint-cdc] Running SpyGlass CDC (cdc_setup → cdc_setup_check → cdc_verify_struct)..."
	@chmod +x scripts/run_spyglass.sh
	@SPYGLASS_STAGE=cdc ./scripts/run_spyglass.sh
	@$(MAKE) --no-print-directory cdc-report
	@echo "[lint-cdc] Done. Report: cdc-report.txt"

lint-report:  ## Aggregate SpyGlass output → lint-report.txt + lint-violations.json
	@python3 scripts/collect_report.py lint

cdc-report:  ## Aggregate SpyGlass output → cdc-report.txt + cdc-violations.json
	@python3 scripts/collect_report.py cdc

clean:  ## Remove intermediate artifacts and reports
	rm -rf spyglass_work
	rm -f spyglass*.log spyglass*.cmd lint-report.txt cdc-report.txt lint-violations.json cdc-violations.json
	find . -maxdepth 3 -name '.spyglass_*' -exec rm -rf {} + 2>/dev/null || true
