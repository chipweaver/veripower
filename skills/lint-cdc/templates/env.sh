# shellcheck shell=sh
# ==============================================================================
# env.sh — lint-cdc stage environment variables.
# Sourced by the Makefile and scripts/ entries. Do not edit MY_TOP placeholder
# post-deploy — the lint-cdc bootstrap verb substitutes it.
# ==============================================================================

# Top module name, substituted by the lint-cdc bootstrap verb.
export TOP="${TOP:-MY_TOP}"

# SpyGlass goal subset selector (lint | cdc | all). The Makefile sets this per
# target; for direct invocation it can be overridden. Default is all
# (lint + CDC in a single session).
export SPYGLASS_STAGE="${SPYGLASS_STAGE:-all}"

# Per-run SpyGlass timeout in seconds.
export SPYGLASS_TIMEOUT="${SPYGLASS_TIMEOUT:-1800}"
