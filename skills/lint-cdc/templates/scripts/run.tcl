# ==============================================================================
# run.tcl — SpyGlass lint / CDC entry (single file, stage-parameterized).
#
# Invocation (from the runs/<N>/ deploy directory, launched by the Makefile):
#   spyglass -64bit -shell -tcl scripts/run.tcl
#
# SPYGLASS_STAGE env var selects the goal subset:
#   lint  — lint/lint_rtl goal only (make lint)
#   cdc   — CDC three-stage goal only (make cdc)
#   all   — lint + CDC in a single session (make all, default)
#
# CDC goals can run independently (each goal does its own elaborate), but
# running lint first lets set_case_analysis converge, so the CDC report
# isn't polluted by test-control-signal noise.
# ==============================================================================

set _stage "all"
if {[info exists ::env(SPYGLASS_STAGE)] && $::env(SPYGLASS_STAGE) ne ""} {
    set _stage $::env(SPYGLASS_STAGE)
}
if {$_stage ne "lint" && $_stage ne "cdc" && $_stage ne "all"} {
    puts stderr "ERROR: unknown SPYGLASS_STAGE='$_stage' (expected lint|cdc|all)"
    exit 1
}

open_project scripts/spyglass_lint.prj

if {$_stage eq "lint" || $_stage eq "all"} {
    current_goal lint/lint_rtl
    source scripts/waiver.tcl
    run_goal
}

if {$_stage eq "cdc" || $_stage eq "all"} {
    current_goal cdc/cdc_setup
    run_goal
    current_goal cdc/cdc_setup_check
    run_goal
    current_goal cdc/cdc_verify_struct
    run_goal
}

exit -force
