# shellcheck shell=sh
# ==============================================================================
# env.sh — power-analysis stage environment variables.
# Sourced by the Makefile and scripts/ entries. Do not edit MY_TOP / MY_MODULE
# placeholders post-deploy — the power bootstrap verb substitutes them.
# ==============================================================================

# Top module and module-directory names, substituted by the power bootstrap verb.
# MODULE is used to resolve simulation TB class names ({MODULE}_tb_pkg /
# {MODULE}_base_test / {MODULE}_<seq>_seq, etc.). MODULE and TOP are usually
# identical but the contract allows them to diverge.
export TOP="${TOP:-MY_TOP}"
export MODULE="${MODULE:-MY_MODULE}"

# External reference paths — MY_SYN_OUT / MY_SIM_DIR / MY_PLAN_DIR are
# substituted at bootstrap with the absolute stage-root paths injected via
# dispatch.json, so paths stay correct regardless of workdir depth (canonical
# Verification/power-analysis/ vs runs/<N>/) without any relpath computation.
export NETLIST="MY_SYN_OUT/${TOP}_syn.v"
export SDC_FILE="MY_SYN_OUT/${TOP}_syn.sdc"
export SDF_FILE="MY_SYN_OUT/${TOP}_syn.sdf"

export TB_DIR="MY_SIM_DIR"
export TB_FILELIST="${TB_DIR}/filelist.f"
export TB_FILELIST_ABS="./tb_filelist_abs.f"
export PLAN_DIR="MY_PLAN_DIR"

export POWER_TESTS_DIR="./scaffold/power_tests"
export POWER_FILELIST="./scaffold/power_filelist.f"

# DUT instance hierarchy — single source for the {TOP}_tb_top/u_dut convention.
# Must match simulation templates/scaffold/tb_top.sv (enforced by
# tests/contracts/test_cross_stage_contracts.py). PT uses '/', VCS -sdf uses '.'.
export TB_TOP="${TOP}_tb_top"
export DUT_INST="u_dut"
export STRIP_PATH="${TB_TOP}/${DUT_INST}"
export VCS_SDF_SCOPE="${TB_TOP}.${DUT_INST}"

# Required env vars.
# Examples:
#   export LIB_V=/home/eda/Foundry/TSMC.90/tsmc090.v
#   export LIB_DB=/home/eda/Foundry/TSMC.90/slow.db
#   export UVM_HOME=/home/eda/UVM/uvm-1.1d
LIB_V="${LIB_V:?ERROR: LIB_V (standard cell Verilog models path) not set.}"
LIB_DB="${LIB_DB:?ERROR: LIB_DB (standard cell Liberty .db path) not set. Must match synthesis stage.}"
UVM_HOME="${UVM_HOME:?ERROR: UVM_HOME not set.}"
export LIB_V LIB_DB UVM_HOME

export VCS_TIMESCALE="-timescale=1ns/1ps"
# VCS 2016: +vcs+initmem+N / +vcs+initreg+N are deprecated. Use compile-time
# +vcs+initreg+random, then pick the actual value at runtime via
# +vcs+initreg=<seed|0|1|random>.
export VCS_INIT_FLAGS="+vcs+initreg+random"
