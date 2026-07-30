# ==============================================================================
# waiver.tcl — SpyGlass lint/CDC waiver definitions.
# Sourced by run.tcl exactly once per session on every SPYGLASS_STAGE (lint, cdc,
# all), so both `waive` entries and `set_option`s here apply to lint and CDC alike.
#
# Waiver format. The -comment is mandatory and the lint-cdc finalize verb BLOCKS
# without it: SpyGlass subtracts a waived message before anything counts it, so this
# text is the only surviving record of what was accepted and why.
#   waive -rules {<rule-id>} \
#         [-file {<file-name>}] \
#         [-msg {<match-string>}] \
#         [-regexp] \
#         -comment "<why this violation is acceptable>"
# ==============================================================================

# ------------------------------------------------------------------------------
# Module-level waiver example (uncomment as needed)
# ------------------------------------------------------------------------------
# waive -rules {W391} \
#       -file {MY_TOP.v} \
#       -msg {clk} \
#       -regexp \
#       -comment "Gating is on the clock port itself, which is the intended structure here"

# ------------------------------------------------------------------------------
# Project-global waivers (rules already reviewed and accepted)
# ------------------------------------------------------------------------------

# W257: RTL contains delay statements (e.g. `#10`). Synthesis ignores them;
# they are used for simulation-only models — accepted.
waive -rules {W257} \
      -comment "Global: synthesis ignores delays — simulation-only, reviewed and accepted. Owner: <name> Date: yyyy-mm-dd"

# W280: nonblocking assignment with delay (e.g. `q <= #1 d`). Simulation-only,
# accepted.
waive -rules {W280} \
      -comment "Global: delay in nonblocking assignment — simulation-only, reviewed and accepted. Owner: <name> Date: yyyy-mm-dd"
