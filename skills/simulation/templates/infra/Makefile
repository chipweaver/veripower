# IPD simulation — VCS compile + regression entry.
#
# make simv     compile (VCS handles incremental compile)
# make smoke    smoke regression suite
# make regress  full regression suite
# make summary  generate review summary (case-results-summary.md)

.PHONY: help simv smoke regress summary coverage clean

help:  ## Show this help message
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

simv:  ## Compile UVM testbench (VCS handles incremental)
	@bash -lc 'source ./env.sh && ./scripts/run_vcs_regression.sh compile'

smoke: simv  ## Run smoke regression suite
	@bash -lc 'source ./env.sh && ./scripts/run_vcs_regression.sh smoke'

regress: simv  ## Run full regression suite
	@bash -lc 'source ./env.sh && ./scripts/run_vcs_regression.sh regress'

summary:  ## Generate case-results.json + case-results-summary.md
	@bash -lc 'source ./env.sh && "$$PYTHON" ./scripts/write_summary.py --verification-dir "$$PWD"'

coverage:  ## Merge per-test coverage to a text report and emit structural-coverage.json
	@bash -lc 'source ./env.sh && \
		urg -dir "$$SIMV.vdb" -dir ./cov_test/*.vdb -report cov_merge -format text && \
		"$$PYTHON" ./scripts/parse_coverage.py --cov-dir ./cov_merge --out ./structural-coverage.json'

clean:  ## Remove intermediate artifacts and reports
	@bash -c 'source ./env.sh && \
		rm -rf out work cov_test "$$RUN_LOG_DIR" && \
		rm -f regression-log.txt case-results.json case-results-summary.md && \
		rm -rf "$$SIMV" "$$SIMV.daidir" csrc ucli.key vc_hdrs.h novas.* verdi* vdCovLog *.vdb *.log urgReport both* cov_merge && \
		rm -f structural-coverage.json'
