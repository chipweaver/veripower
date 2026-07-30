# ==============================================================================
# waiver.tcl — SpyGlass lint/CDC waiver definitions.
# Sourced by run.tcl exactly once per session on every SPYGLASS_STAGE (lint, cdc,
# all), so both `waive` entries and `set_option`s here apply to lint and CDC alike.
#
# Waiver format:
#   waive -rules {<rule-id>} \
#         [-file {<file-name>}] \
#         [-msg {<match-string>}] \
#         [-regexp] \
#         -comment "<rationale>. Owner: <name> Date: <yyyy-mm-dd>"
#
# Common rule IDs:
#   W391           — unintended clock gating
#   W528           — inconsistent drive strength
#   W240           — case statement missing a default branch
#   STARC05-1.3.1  — latch inference
#   CDC-*          — CDC-related rules
# ==============================================================================

# ------------------------------------------------------------------------------
# Module-level waiver example (uncomment as needed)
# ------------------------------------------------------------------------------
# waive -rules {W391} \
#       -file {MY_TOP.v} \
#       -msg {clk} \
#       -regexp \
#       -comment "Clock port — expected behavior, not a W391 violation. Owner: <name> Date: yyyy-mm-dd"

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
