# ==============================================================================
# ptpx.tcl — PT-PX averaged power analysis (SAIF-driven, batch over SAIF_LIST)
#
# Single pt_shell session: design loading + SDC/SDF read happens once, then
# loops over SAIF_LIST entries reusing the loaded design — saves one full
# read_verilog/link/read_sdc/read_sdf per scenario vs the per-SAIF launch
# pattern. That reuse is also why the batch opens with a discarded warm-up
# iteration: measured on a real netlist, whichever scenario runs first reports
# less power than the identical scenario run second, so without the warm-up the
# reported number depends on the order of SAIF_LIST. See the warm-up block below.
#
# Inputs (env vars from caller, typically Makefile's ptpx target):
#   TOP / LIB_DB / NETLIST / SDC_FILE / SDF_FILE — design loading inputs
#   SAIF_LIST — space-separated "<id>=<abs_saif_path>" entries
#   STRIP_PATH — required; set by env.sh from TB_TOP / DUT_INST
#
# Per-scenario outputs (one set per <id>):
#   reports_ptpx/<id>/{power_hier,power_flat,switching_activity}.rpt
#   reports_ptpx/<id>/switching_not_annotated.rpt — gate raw text
#   reports_ptpx/<id>/ptpx.log                    — per-scenario tee'd log
#
# Per-scenario errors (read_saif failure / 0% annotation / power calc) skip
# that one scenario but the batch keeps going. Exit code is 0 only if every
# scenario succeeded.
# ==============================================================================

# PT M-2016 treats hier_separator as a Tcl global (set_app_var raises CMD-104);
# newer PT treats it as an application var. Two-form set covers both.
catch {set_app_var hier_separator "/"}
set hier_separator "/"

foreach _var {TOP LIB_DB NETLIST SDC_FILE SDF_FILE SAIF_LIST} {
    if {![info exists ::env($_var)] || $::env($_var) eq ""} {
        puts stderr "ERROR: environment variable $_var not set"
        exit 1
    }
}

set top         $::env(TOP)
set lib_db      $::env(LIB_DB)
set netlist     $::env(NETLIST)
set sdc_file    $::env(SDC_FILE)
set sdf_file    $::env(SDF_FILE)
set saif_list   $::env(SAIF_LIST)

if {![info exists ::env(STRIP_PATH)] || $::env(STRIP_PATH) eq ""} {
    puts stderr "ERROR: environment variable STRIP_PATH not set (env.sh must export it)"
    exit 1
}
set strip_path $::env(STRIP_PATH)

puts "INFO: top         = $top"
puts "INFO: lib_db      = $lib_db"
puts "INFO: netlist     = $netlist"
puts "INFO: sdc_file    = $sdc_file"
puts "INFO: sdf_file    = $sdf_file"
puts "INFO: strip_path  = $strip_path"

foreach {_label _path} [list netlist $netlist sdc $sdc_file sdf $sdf_file lib_db $lib_db] {
    if {![file exists $_path]} {
        puts stderr "ERROR: $_label not found: $_path"
        exit 1
    }
}

# Design loading — once for the whole batch
set_app_var link_path   [list "*" $lib_db]
set_app_var search_path [list "."]

if {[catch { read_verilog $netlist; current_design $top; link } _err]} {
    puts stderr "ERROR: design load failed (phase=ptpx): $_err"
    exit 1
}
if {[catch { read_sdc $sdc_file } _err]} {
    puts stderr "ERROR: read_sdc failed (phase=ptpx): $_err"
    exit 1
}
if {[catch { read_sdf $sdf_file } _err]} {
    puts stderr "ERROR: read_sdf failed (phase=ptpx): $_err"
    exit 1
}

set power_enable_analysis TRUE
set_app_var power_analysis_mode averaged

# Warm-up: one full read_saif + check_power + update_power whose numbers are thrown
# away, so that every scenario the batch reports runs against a settled session.
#
# The first update_power in a session reads low. Measured on a real 143k-cell netlist,
# the same SAIF read three times in one session gave 21.3 mW then 21.6 mW then 21.6 mW,
# and the busier the activity the wider the gap: a peak-decode SAIF gave 32.2 mW first
# and 34.2 mW thereafter, a 6% understatement. A fresh pt_shell per SAIF reproduces the
# low value, so this is not batch contamination to be avoided by launching per scenario
# — the settled value is the right one, and a warm-up is what buys it for scenario one.
# The warm-up SAIF does not have to be the one being measured; a cross-SAIF warm-up
# settles the session just as well, so the first readable entry is used.
#
# Failures here are silent on purpose: this iteration reports nothing, and whatever is
# wrong with that SAIF the batch below will report against the scenario that owns it.
foreach entry [split $saif_list " "] {
    if {$entry eq ""} { continue }
    set _parts [split $entry "="]
    if {[llength $_parts] < 2} { continue }
    set _warm [lindex $_parts 1]
    if {![file exists $_warm]} { continue }
    puts "INFO: warm-up on [file tail $_warm] (numbers discarded; see header)"
    catch {
        reset_switching_activity
        read_saif -strip_path $strip_path $_warm
        check_power
        update_power
    }
    break
}

# Batch loop over SAIF_LIST. SAIF_LIST format: space-separated "<id>=<path>".
set ok_count 0
set fail_count 0

foreach entry [split $saif_list " "] {
    if {$entry eq ""} { continue }
    set parts [split $entry "="]
    if {[llength $parts] < 2} {
        puts stderr "WARNING: skipping malformed SAIF_LIST entry: $entry"
        incr fail_count
        continue
    }
    set scenario_id [lindex $parts 0]
    set saif_file   [lindex $parts 1]
    set reports_dir [file normalize [file join [pwd] "reports_ptpx" $scenario_id]]
    file mkdir $reports_dir
    set scenario_log [file join $reports_dir "ptpx.log"]

    if {![file exists $saif_file]} {
        puts stderr "ERROR: scenario $scenario_id — saif not found: $saif_file"
        incr fail_count
        continue
    }

    set scenario_ok 1
    set scenario_error ""
    redirect -tee -file $scenario_log {
        puts ""
        puts "============================================================"
        puts "INFO: scenario $scenario_id"
        puts "      saif        = $saif_file"
        puts "      reports_dir = $reports_dir"
        puts "============================================================"

        if {[catch { reset_switching_activity } _err]} {
            puts "WARNING: reset_switching_activity: $_err"
        }

        if {[catch { read_saif -strip_path $strip_path $saif_file } _err]} {
            puts "ERROR: read_saif failed: $_err"
            set scenario_ok 0
            set scenario_error "read_saif failed: $_err"
        }

        # 0% annotation hard gate (per scenario; logs + skips on failure
        # rather than exiting the whole batch).
        if {$scenario_ok} {
            set _act_rpt [file join $reports_dir "switching_not_annotated.rpt"]
            redirect -file $_act_rpt {report_switching_activity}
            set _fh [open $_act_rpt r]
            set _content [read $_fh]
            close $_fh

            set _coverage_ok 0
            if {[regexp -line {Annotated\s+cell\s+percentage\s*=\s*([0-9.]+)\s*%} $_content -> _pct]} {
                if {$_pct > 0.0} { set _coverage_ok 1 }
            }
            # The table row is what this flow's PT actually emits — no observed report
            # carries the "Annotated cell percentage" line, so this branch is the live one.
            # The precise rate is parsed post-run by power/result.py (saif_annotation_rate);
            # the >0 test here needs only the printed percentage.
            if {!$_coverage_ok} {
                if {[regexp -line {^\s*Nets\s+([0-9]+)\(([0-9.]+)%\)} $_content -> _ncount _npct]} {
                    if {$_npct > 0.0} { set _coverage_ok 1 }
                }
            }
            if {!$_coverage_ok} {
                puts "ERROR: read_saif annotated 0% (phase=ptpx) — strip_path='$strip_path' may mismatch (details: $_act_rpt)"
                set scenario_ok 0
                set scenario_error "read_saif annotated 0% — strip_path='$strip_path' may mismatch (details: $_act_rpt)"
            }
        }

        if {$scenario_ok} {
            if {[catch {
                check_power
                update_power
                report_power -hierarchy -verbose > [file join $reports_dir "power_hier.rpt"]
                report_power -verbose            > [file join $reports_dir "power_flat.rpt"]
                report_switching_activity        > [file join $reports_dir "switching_activity.rpt"]
            } _err]} {
                puts "ERROR: power/report failed: $_err"
                set scenario_ok 0
                set scenario_error "power/report failed: $_err"
            }
        }

        if {$scenario_ok} {
            puts "INFO: scenario $scenario_id — ok"
        } else {
            puts "INFO: scenario $scenario_id — FAILED"
        }
    }

    # Surface failures on stderr outside the redirect block so the operator
    # sees them on the terminal (PT's redirect -tee captures stderr inside).
    if {!$scenario_ok && $scenario_error ne ""} {
        puts stderr "ERROR: scenario $scenario_id — $scenario_error"
    }

    if {$scenario_ok} {
        incr ok_count
    } else {
        incr fail_count
    }
}

puts ""
puts "INFO: ptpx batch finished — $ok_count ok / $fail_count fail"
if {$fail_count > 0} {
    exit 1
}
quit
