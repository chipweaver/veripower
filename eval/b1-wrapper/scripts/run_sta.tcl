# ==============================================================================
# run_sta.tcl — PrimeTime STA on the post-synthesis netlist (bare).
#   pt_shell -f scripts/run_sta.tcl
# Env (from env.sh): TOP, LIB_DB, NETLIST, SDC (relative to the wrapper dir).
# ==============================================================================
set top     $::env(TOP)
set lib_db  $::env(LIB_DB)
set netlist $::env(NETLIST)
set sdc     $::env(SDC)

set link_library   "* $lib_db"
set target_library $lib_db
set report_default_significant_digits 4

read_verilog $netlist
link_design  $top
read_sdc     $sdc

redirect timing-report.txt {
    report_timing -delay max
    report_timing -delay min
    check_timing
}
exit
