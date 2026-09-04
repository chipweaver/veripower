# PrimeTime STA — independent timing verification of the post-synthesis netlist.
# MODULE_ROOT / WORKDIR are shown tree-root-relative for a stable, portable fixture; the
# live timing bootstrap verb substitutes ABSOLUTE paths and runs from the workdir
# (cd <workdir> && pt_shell -f run_sta.tcl).
set MODULE_ROOT asic/tpu_top
set WORKDIR     asic/tpu_top/Design/timing-analysis/runs/3
source $WORKDIR/config.tcl                  ;# sets TOP and LIB_DB

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
