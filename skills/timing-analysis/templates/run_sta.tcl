# PrimeTime STA — independent timing verification of the post-synthesis netlist.
# Invoked from the workdir: cd <workdir> && pt_shell -f run_sta.tcl
# NETLIST_DIR / WORKDIR are ABSOLUTE paths, substituted by the timing bootstrap verb.
set NETLIST_DIR MY_NETLIST_DIR
set WORKDIR     MY_WORKDIR
source $WORKDIR/config.tcl                  ;# sets TOP and LIB_DB

set link_library   "* $LIB_DB"
set target_library $LIB_DB
set report_default_significant_digits 4     ;# MANDATORY — keeps recorded slack correct (sub-rounding violations)

# Each of these returns 1 on success and 0 on failure, and none of them raises — so
# without the gates pt_shell runs on to the reports and ends at `exit`, which is status 0.
# A netlist that did not read, or a library that is not there, then reaches the parser as a
# report saying "No constrained paths": well-formed, unparseable, and indistinguishable from
# an SDC that constrained nothing. Named here, where the cause is still known.
if {![read_verilog $NETLIST_DIR/out/${TOP}_syn.v]} {
    puts stderr "ERROR: read_verilog failed for $NETLIST_DIR/out/${TOP}_syn.v"
    exit 1
}
if {![link_design $TOP]} {
    puts stderr "ERROR: link_design failed for $TOP - unresolved references, or LIB_DB does not carry the cells this netlist names (config.tcl: $LIB_DB)"
    exit 1
}
if {![read_sdc $NETLIST_DIR/out/${TOP}_syn.sdc]} {
    puts stderr "ERROR: read_sdc failed for $NETLIST_DIR/out/${TOP}_syn.sdc"
    exit 1
}

redirect $WORKDIR/timing-report.txt {
    report_timing -delay max                ;# setup — worst path(s), MET/VIOLATED marker
    report_timing -delay min                ;# hold  — worst path(s), MET/VIOLATED marker
    check_timing                            ;# for the reader: what the SDC left open
    # The gated pair. Every output port bit is a data port, so out_setup's Total is the
    # count of them this run actually timed, and the line below is the count it should
    # have. Inputs have no such expectation — clock and async-reset ports carry no input
    # delay by design, and nothing here can tell which inputs those are.
    puts "Boundary output bits: [sizeof_collection [all_outputs]]"
    report_analysis_coverage
}
exit
