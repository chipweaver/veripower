# ==============================================================================
# run_spyglass.tcl — SpyGlass lint / CDC (bare, stage-parameterized).
#   spyglass -64bit -shell -tcl scripts/run_spyglass.tcl
# SPYGLASS_STAGE env: lint | cdc | all (default all).
# ==============================================================================
set _stage "all"
if {[info exists ::env(SPYGLASS_STAGE)] && $::env(SPYGLASS_STAGE) ne ""} {
    set _stage $::env(SPYGLASS_STAGE)
}
open_project scripts/spyglass.prj
if {$_stage eq "lint" || $_stage eq "all"} {
    current_goal lint/lint_rtl
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
