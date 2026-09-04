# shellcheck shell=sh
# ==============================================================================
# env.sh — synthesis stage environment variables.
# Sourced by the Makefile before launching dc_shell / pt_shell.
# After deploy, MY_TOP is substituted by synthesis bootstrap.
# Must be POSIX-sh compatible — do not use ${BASH_SOURCE} or other bashisms.
# ==============================================================================

# Top module name, substituted by synthesis bootstrap.
TOP="${TOP:-MY_TOP}"

# Standard-cell library path — must come from the environment.
# Example: export LIB_DB=/home/eda/Foundry/TSMC.90/slow.db
LIB_DB="${LIB_DB:?ERROR: LIB_DB not set. Export it before running make.}"
# The wire load model this library offers for a block of this size. Required, with no
# default: a library carries several (tsmc090_wl10..wl50, smic18_wl10..wl50) and typically
# declares neither a default nor a selection group, so nothing picks one unless you do —
# and with none picked DC reports no net interconnect at all, which reaches PT-PX as zero
# net switching power. Their estimates differ by the block size they were calibrated for,
# so this is a per-block choice: `report_lib <lib>` lists what the library has.
# Example: export WIRE_LOAD_MODEL=tsmc090_wl10
WIRE_LOAD_MODEL="${WIRE_LOAD_MODEL:?ERROR: WIRE_LOAD_MODEL not set. Export it before running make (report_lib lists the models a library has).}"
[ -f "$LIB_DB" ] || {
	echo "ERROR: LIB_DB invalid or not found: $LIB_DB" >&2
	exit 1
}

export TOP LIB_DB WIRE_LOAD_MODEL
