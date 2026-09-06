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
#
# scripts/waiver.tcl is sourced exactly once per session, whichever subset runs,
# so waivers and set_options apply to lint and CDC alike.
# ==============================================================================

set _stage "all"
if {[info exists ::env(SPYGLASS_STAGE)] && $::env(SPYGLASS_STAGE) ne ""} {
    set _stage $::env(SPYGLASS_STAGE)
}
if {$_stage ne "lint" && $_stage ne "cdc" && $_stage ne "all"} {
    puts stderr "ERROR: unknown SPYGLASS_STAGE='$_stage' (expected lint|cdc|all)"
    exit 1
}

# Everything below runs inside one catch. SpyGlass RAISES on the failures that stop a run
# — a project whose sourcelist is not there, a goal the methodology does not have — but the
# process still ends at status 0, so an unwrapped script that read nothing exits exactly
# like one that linted cleanly, and the first sign of it is `collect_report.py` reporting
# no source report: true, and about the wrong thing. Warnings are NOT such a failure:
# `run_goal` returns `0 {Rule-checking completed with warnings}` on a normal run, and the
# report those warnings land in is this stage's deliverable.
if {[catch {
    open_project scripts/spyglass_lint.prj

    # Measured on SpyGlass_vL-2016.06: a `waive` issued while a goal is current
    # applies to THAT goal only. Sourced after `current_goal lint/lint_rtl` it never
    # reached the CDC goals, on any SPYGLASS_STAGE; sourced after
    # `current_goal cdc/cdc_setup` it did not reach cdc_verify_struct either. Sourced
    # here, before any goal is current, it applies to every goal in the session and
    # leaves lint waiving unchanged.
    source scripts/waiver.tcl

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
} _err]} {
    puts stderr "ERROR: SpyGlass stopped (SPYGLASS_STAGE=$_stage): $_err"
    exit 1
}

exit -force
