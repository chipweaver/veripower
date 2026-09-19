# Investigate coverage gaps

Read the DUT instance subtree in `structural-coverage.json` (`per_instance`) and the original URG
reports under `cov_merge/`. For the generated TB the DUT is `<top>_tb_top.u_dut`, using the scaffold's
RTL `top`. Compare bounded coverage with the requirements; investigate missing measurements and
instrumentation.

Use uncovered source locations, RTL conditions, stimuli and checks to identify the cause. Keep
expected behavior grounded in the independent task requirements. Use focused experiments where
needed; absence from the testpoint list does not establish the cause.

Repair the responsible stimulus, check, plan or implementation. Existing requirements already
authorize tests needed to establish them. Recompile affected sources and obtain the regression
and coverage evidence needed for the result being claimed.

Support exclusions with technical evidence under the measurement's stated scope. Retain the
reasoning and effective coverage configuration with the reports. A successful reachability probe
refutes an unreachable claim; a failed attempt to reach an item does not prove it unreachable.
An authorized acceptance change establishes a new scope, which the resulting claim must state.
