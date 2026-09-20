# One calculation per process. The caller supplies activity and output paths.
foreach setting_name {TOP LIB_DB NETLIST SDC_FILE STRIP_PATH SAIF_FILE REPORTS_DIR} {
    if {![info exists ::env($setting_name)] || $::env($setting_name) eq ""} {
        puts stderr "ERROR: $setting_name is required (phase=ptpx)"
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
    set reports_dir $::env(REPORTS_DIR)
    redirect -file [file join $reports_dir switching_activity.rpt] {report_switching_activity}
    set report_handle [open [file join $reports_dir switching_activity.rpt] r]
    set activity_report_text [read $report_handle]
    close $report_handle
    if {![regexp -line {^\s*Nets\s+([0-9]+)\(([0-9.]+)%\)} $activity_report_text annotation_match annotated_net_count annotated_net_percent] || $annotated_net_count == 0} {
        error "no SAIF net annotation; check capture scope and STRIP_PATH"
    }
    redirect -file [file join $reports_dir check_power.rpt] {check_power}
    update_power
    redirect -file [file join $reports_dir power_hier.rpt] {report_power -hierarchy -verbose}
    redirect -file [file join $reports_dir power_flat.rpt] {report_power -verbose}
} tool_error]} {
    puts stderr "ERROR: $tool_error (phase=ptpx)"
    exit 1
}
exit 0
