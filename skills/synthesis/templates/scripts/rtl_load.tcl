# ==============================================================================
# rtl_load.tcl — RTL ingest (analyze form).
#
# This file is a template placeholder. After deploy, synthesis bootstrap
# regenerates it from Design/rtl-design/rtl-files.json with:
#   1. set_app_var search_path — each child's incdirs, prefixed with the absolute
#      rtl-design root, appended.
#   2. analyze invocations    — one per RTL file in dependency order.
# ==============================================================================

analyze -format sverilog -define SYNTHESIS [list MY_RTL_DIR/MY_TOP.v]
