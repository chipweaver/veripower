# shellcheck shell=sh

MODULE="${MODULE:-tpu_top}"
TOP="${TOP:-tpu_top}"
TB_TOP="${TB_TOP:-${TOP}_tb_top}"
SIM_TOOL="${SIM_TOOL:-vcs}"
PYTHON="${PYTHON:-python3}"
# UVM_HOME: must be set via environment before running make.
# Example: export UVM_HOME=/home/eda/UVM/uvm-1.1d
UVM_HOME="${UVM_HOME:?ERROR: UVM_HOME not set. Export it before running make.}"

SPEC_DIR="${SPEC_DIR:-../../../../Design/specification}"
RTL_DIR="${RTL_DIR:-../../../../Design/rtl-design}"
TESTLIST_JSON="${TESTLIST_JSON:-tests/testlist.json}"
SIMV="${SIMV:-simv}"
COMPILE_LOG="${COMPILE_LOG:-com.log}"
RUN_LOG_DIR="${RUN_LOG_DIR:-logs}"
VCS_COV="${VCS_COV:--cm line+cond+branch+tgl+fsm}"
# Pin the C/C++ compiler VCS uses for the final simv link. The host default
# compiler (gcc 14.x) does LTO on the prebuilt Verdi pli.a (LTO bytecode v2.2)
# and the link aborts with an LTO-version mismatch. gcc/g++ 4.8 matches the
# Verdi 2016 prebuilt LTO version, so the link succeeds.
VCS_CC="${VCS_CC:-gcc-4.8}"
VCS_CPP="${VCS_CPP:-g++-4.8}"
SEED="${SEED:-$($PYTHON -c 'from random import randint; print(randint(0,99999999))')}"

export MODULE TOP TB_TOP SIM_TOOL PYTHON UVM_HOME
export SPEC_DIR RTL_DIR TESTLIST_JSON
export SIMV COMPILE_LOG RUN_LOG_DIR VCS_COV SEED
export VCS_CC VCS_CPP
