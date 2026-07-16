# shellcheck shell=sh

MODULE="${MODULE:-MY_MODULE}"
TOP="${TOP:-MY_TOP}"
TB_TOP="${TB_TOP:-${TOP}_tb_top}"
SIM_TOOL="${SIM_TOOL:-vcs}"
PYTHON="${PYTHON:-python3}"
# UVM_HOME: must be set via environment before running make.
# Example: export UVM_HOME=/home/eda/UVM/uvm-1.1d
UVM_HOME="${UVM_HOME:?ERROR: UVM_HOME not set. Export it before running make.}"

TESTLIST_JSON="${TESTLIST_JSON:-tests/testlist.json}"
SIMV="${SIMV:-simv}"
COMPILE_LOG="${COMPILE_LOG:-com.log}"
RUN_LOG_DIR="${RUN_LOG_DIR:-logs}"
VCS_COV="${VCS_COV:--cm line+cond+branch+tgl+fsm}"
SEED="${SEED:-$($PYTHON -c 'from random import randint; print(randint(0,99999999))')}"

export MODULE TOP TB_TOP SIM_TOOL PYTHON UVM_HOME
export TESTLIST_JSON
export SIMV COMPILE_LOG RUN_LOG_DIR VCS_COV SEED
