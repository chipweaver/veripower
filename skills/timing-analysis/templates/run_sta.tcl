# PrimeTime STA — independent timing verification of the post-synthesis netlist.
# Invoked from the tree root (dir containing asic/): pt_shell -f MY_WORKDIR/run_sta.tcl
# MY_MODULE / MY_WORKDIR are substituted by bootstrap_timing_analysis.sh.
set MODULE_ROOT asic/MY_MODULE
set WORKDIR     MY_WORKDIR
source $WORKDIR/config.tcl                  ;# sets TOP and LIB_DB

if {![info exists LIB_DB] || $LIB_DB eq "FILL_IN_LIB_DB_PATH"} {
    error "LIB_DB not set — edit $WORKDIR/config.tcl"
}
set link_library   "* $LIB_DB"
set target_library $LIB_DB
set report_default_significant_digits 4     ;# MANDATORY — keeps recorded slack correct (sub-rounding violations)

read_verilog $MODULE_ROOT/Design/synthesis/out/${TOP}_syn.v
link_design  $TOP
read_sdc     $MODULE_ROOT/Design/synthesis/out/${TOP}_syn.sdc

redirect $WORKDIR/timing-report.txt {
    report_timing -delay max                ;# setup — worst path(s), MET/VIOLATED marker
    report_timing -delay min                ;# hold  — worst path(s), MET/VIOLATED marker
    check_timing                            ;# coverage (recorded by the parser, not gated)
}
exit
