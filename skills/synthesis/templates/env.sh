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
# Which interconnect estimate this block is synthesized against, or `none` for no estimate.
# Required and without a default, because the choice moves both numbers this stage is judged
# on and nothing else records that it was made. Measured on three designs against a TSMC 90
# library: going from `none` to the SMALLEST bucket cost OpenTitan's i2c its whole 2.47 ns
# of setup margin, and the largest bucket raised total cell area by 18% to 65%. A library
# carries several models (tsmc090_wl10..wl50, smic18_wl10..wl50), declares no default and
# no selection group, and calibrates each to a block size — so no bucket is the right one to
# assume on your behalf. `none` is a legal answer and is what OpenTitan and mflowgen do;
# a physical flow reads real parasitics instead. `report_lib <lib>` lists what the library
# has.
# Example: export WIRE_LOAD_MODEL=none      (or tsmc090_wl10)
WIRE_LOAD_MODEL="${WIRE_LOAD_MODEL:?ERROR: WIRE_LOAD_MODEL not set. Export it before running make — a model name (report_lib lists them) or $(none).}"
[ -f "$LIB_DB" ] || {
	echo "ERROR: LIB_DB invalid or not found: $LIB_DB" >&2
	exit 1
}

export TOP LIB_DB WIRE_LOAD_MODEL
