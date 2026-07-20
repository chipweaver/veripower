# =============================================================================
# FIXED §1.3(d) timing bar for fa_core_indep adjudication.
#
# This is the JUDGE's constraint, NOT an arm's own SDC — supplied to
# adjudicate.py --fixed and used verbatim for BOTH DC synth (SDC_IN) and PT STA,
# identically for every arm (§1.3 symmetry: an arm's self-written lax SDC must
# never buy a free timing pass).
#
# Derived from the spec (asic/fa_core_indep/brainstorm.md, "Clocks & Reset"):
# single clock `clk` @ 100 MHz / 10 ns, async active-low `rst_n`, single domain.
# The spec pins ONLY the 10 ns clock — timing is closure-only, there is no
# performance/latency target — so this bar is "close 10 ns", not a tighter
# frequency. The I/O budget below is a conventional modest allocation (the design
# is internally reg-reg bound on the fp32 datapath, so the I/O value is immaterial
# to the verdict); it is identical for both arms.
#
# Port-name-agnostic beyond clk/rst_n (uses all_inputs/all_outputs), so this one
# file judges any implementation conforming to the pinned top interface.
# =============================================================================

create_clock -name clk -period 10.0 [get_ports clk]
set_clock_uncertainty -setup 0.2 [all_clocks]
set_clock_uncertainty -hold  0.0 [all_clocks]

# clk/rst_n carry no data arrival time; every other port is data on `clk`.
set ports_no_delay [get_ports {clk rst_n}]
set data_inputs [remove_from_collection [all_inputs] $ports_no_delay]
if {[sizeof_collection $data_inputs] > 0} { set_input_delay 0.2 -clock clk $data_inputs }
if {[sizeof_collection [all_outputs]] > 0} { set_output_delay 0.2 -clock clk [all_outputs] }
set_drive 0    [all_inputs]
set_load  0.05 [all_outputs]
