# ==============================================================================
# waiver.tcl — SpyGlass lint/CDC waiver definitions.
# Sourced by run.tcl exactly once per session on every SPYGLASS_STAGE (lint, cdc,
# all), so both `waive` entries and `set_option`s here apply to lint and CDC alike.
#
# Record why a waiver is acceptable in -comment, citing evidence where needed.
# Review the messages it actually waives in the native reports against the task's
# waiver policy. Finalize does not judge the reasoning.
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
