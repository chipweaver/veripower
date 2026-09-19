# One calculation per process. The caller supplies activity and output paths.
foreach var {TOP LIB_DB NETLIST SDC_FILE STRIP_PATH SAIF_FILE REPORTS_DIR} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        puts stderr "ERROR: $var is required (phase=ptpx)"
        exit 1
    }
}
if {[catch {
    foreach path [concat $::env(LIB_DB) [list $::env(NETLIST) $::env(SDC_FILE) $::env(SAIF_FILE)]] {
        if {![file readable $path]} {error "input unreadable: $path"}
    }
    set power_enable_analysis true
    set power_analysis_mode averaged
    set_app_var link_path [concat [list "*"] $::env(LIB_DB)]
    if {![read_verilog $::env(NETLIST)]} {error "read_verilog failed"}
    if {![link_design $::env(TOP)]} {error "link_design failed"}
    if {![read_sdc $::env(SDC_FILE)]} {error "read_sdc failed"}
    update_timing
    read_saif -strip_path $::env(STRIP_PATH) $::env(SAIF_FILE)
    set reports $::env(REPORTS_DIR)
    redirect -file [file join $reports switching_activity.rpt] {report_switching_activity}
    set fh [open [file join $reports switching_activity.rpt] r]
    set activity [read $fh]
    close $fh
    if {![regexp -line {^\s*Nets\s+([0-9]+)\(([0-9.]+)%\)} $activity -> count percent] || $count == 0} {
        error "no SAIF net annotation; check capture scope and STRIP_PATH"
    }
    redirect -file [file join $reports check_power.rpt] {check_power}
    update_power
    redirect -file [file join $reports power_hier.rpt] {report_power -hierarchy -verbose}
    redirect -file [file join $reports power_flat.rpt] {report_power -verbose}
} message]} {
    puts stderr "ERROR: $message (phase=ptpx)"
    exit 1
}
exit 0
