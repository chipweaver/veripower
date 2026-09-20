# shellcheck shell=sh

MODULE="${MODULE:-MY_MODULE}"
TOP="${TOP:-MY_TOP}"
TB_TOP="${TB_TOP:-${TOP}_tb_top}"
PYTHON="${PYTHON:-python3}"
# UVM_HOME is required for compilation and simulation, not report processing.
# Example: export UVM_HOME=/home/eda/UVM/uvm-1.1d
UVM_HOME="${UVM_HOME:-}"

TESTLIST_JSON="${TESTLIST_JSON:-tests/testlist.json}"
SIMV="${SIMV:-simv}"
# Where the ELABORATION coverage database goes. Naming it is not cosmetic: given no
# -cm_dir at compile, VCS derives the name from the simulator's argv[0] at run time, so
# the stage silently depends on whatever the caller invokes the binary as — a wrapper
# that re-execs it under another name then makes every coverage run abort at time 0.
COV_DB="${COV_DB:-cov_elab}"
COMPILE_LOG="${COMPILE_LOG:-com.log}"
RUN_LOG_DIR="${RUN_LOG_DIR:-logs}"
VCS_COV="${VCS_COV:--cm line+cond+branch+tgl+fsm}"
SEED="${SEED:-$($PYTHON -c 'from random import randint; print(randint(0,99999999))')}"

export MODULE TOP TB_TOP PYTHON UVM_HOME
export TESTLIST_JSON
export SIMV COV_DB COMPILE_LOG RUN_LOG_DIR VCS_COV SEED
