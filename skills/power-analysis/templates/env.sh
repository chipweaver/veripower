# shellcheck shell=sh
# Sourced from this run's working directory. Edit for the actual experiment.
export TOP=@TOP@
export NETLIST=@NETLIST@
export SDC_FILE=@SDC@
export SDF_FILE=@SDF@

# Set LIB_DB (a Tcl list of linked .db paths) and STRIP_PATH for PT-PX here
# or in the calling environment. STRIP_PATH is the captured DUT hierarchy.
# The experiment's compile/run scripts own simulator, model and service setup.
