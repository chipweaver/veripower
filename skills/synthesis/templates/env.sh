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
[ -f "$LIB_DB" ] || {
	echo "ERROR: LIB_DB invalid or not found: $LIB_DB" >&2
	exit 1
}

export TOP LIB_DB
