# ==============================================================================
# rtl_load.tcl — RTL ingest (analyze form).
#
# This file is a template placeholder. After deploy, synthesis bootstrap
# regenerates it from Design/rtl-design/filelist.txt with:
#   1. set_app_var search_path — expand +incdir+ entries (prepend ${RTL_REL_DIR}/) and append.
#   2. analyze invocations    — one per RTL file in dependency order.
# ==============================================================================

analyze -format sverilog -define SYNTHESIS [list MY_RTL_DIR/MY_TOP.v]
