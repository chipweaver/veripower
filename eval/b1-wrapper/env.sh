# shellcheck shell=sh
# ==============================================================================
# env.sh — generic EDA tool environment for the bare-tool wrapper.
# Sourced by the Makefile before invoking each tool. Fill in / export the
# design-specific values (TOP, NETLIST, ...) for YOUR design before running.
# This file contains only generic tool-level variables — no orchestration.
# ==============================================================================

# Top module name of the design under test (set to yours).
export TOP="${TOP:-accum}"

# Standard-cell library (.db for DC/PT, .v models for gate-level sim).
export LIB_DB="${LIB_DB:?ERROR: LIB_DB (std-cell .db) not set. Export it before make.}"
export LIB_V="${LIB_V:-}"

# UVM install (for vcs UVM DPI compile).
export UVM_HOME="${UVM_HOME:?ERROR: UVM_HOME not set. Export it before make.}"

# Post-synthesis products consumed by STA (produced by `make synth` into ./out/).
export NETLIST="${NETLIST:-out/${TOP}_syn.v}"
export SDC="${SDC:-out/${TOP}_syn.sdc}"

# VCS coverage flags (generic; tune as you like).
export VCS_COV="${VCS_COV:--cm line+cond+branch+tgl+fsm}"
