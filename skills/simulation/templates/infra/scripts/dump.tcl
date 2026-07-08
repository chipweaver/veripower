# UCLI FSDB dump — full-hierarchy waveform of one test run, via $fsdbDumpvars.
# Verified form (VCS L-2016.06 + Verdi, veripower-eda, 2026-07-08): a quoted
# call with the SV '$' escaped, so Tcl substitutes the env-derived path but
# passes '$fsdbDumpfile'/'$fsdbDumpvars' literally to the simulator. A braced
# `call {...}` does NOT work — braces suppress Tcl substitution, so the literal
# string "$_fsdb" reaches the simulator and no per-test file is written.
# The caller (run_vcs_regression.sh) exports IPD_FSDB_FILE per test; env.sh
# already exports TB_TOP. Per-run toggle: dump only when IPD_FSDB_FILE is set.
if {[info exists ::env(IPD_FSDB_FILE)] && $::env(IPD_FSDB_FILE) ne ""} {
    set _fsdb $::env(IPD_FSDB_FILE)
    set _top  $::env(TB_TOP)
    call "\$fsdbDumpfile(\"$_fsdb\")"
    call "\$fsdbDumpvars(0, $_top)"
}
run
quit
