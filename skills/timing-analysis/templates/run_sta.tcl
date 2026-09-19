# PrimeTime STA — independent timing verification of the post-synthesis netlist.
# Invoked from the workdir: cd <workdir> && pt_shell -f run_sta.tcl
# Input locations come from config.tcl; outputs stay in the calculation directory.
source [file join [pwd] config.tcl]
foreach name {TOP LIB_DB NETLIST_DIR} {
    if {![info exists $name] || [set $name] eq ""} {
        puts stderr "ERROR: $name is not set in config.tcl"
        exit 1
    }
}
puts "Library: $LIB_DB"
set WORKDIR [pwd]

set target_library [list $LIB_DB]
set link_library [concat [list "*"] $target_library]
set report_default_significant_digits 4

# These commands return 0 on failure without raising a Tcl error.
if {![read_verilog $NETLIST_DIR/out/${TOP}_syn.v]} {
    puts stderr "ERROR: read_verilog failed for $NETLIST_DIR/out/${TOP}_syn.v"
    exit 1
}
if {![link_design $TOP]} {
    puts stderr "ERROR: link_design failed for $TOP - unresolved references, or LIB_DB does not carry the cells this netlist names (LIB_DB: $LIB_DB)"
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
    # out_setup Total includes untested checks; count agreement is not timing coverage.
    puts "Boundary output bits: [sizeof_collection [all_outputs]]"
    report_analysis_coverage
}
exit
