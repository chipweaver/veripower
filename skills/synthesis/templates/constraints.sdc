# ==============================================================================
# constraints.sdc — synthesis timing-constraint template.
# Top module: MY_TOP
# After deployment, fill out complete constraints per design.md §1.4 interface
# table and actual port names. This file is also reused as STA input.
# ==============================================================================

# --- Clock definitions ---
# Adjust port name and target frequency. -period unit is ns.
create_clock -name clk -period 10.0 [get_ports clk]

set_clock_uncertainty -setup 0.2 [all_clocks]
set_clock_uncertainty -hold  0.0 [all_clocks]   ;# pre-CTS hold = 0; replace with measured skew after CTS

# Multi-clock example (uncomment as needed):
# create_clock -name clk2 -period 20.0 [get_ports clk2]
# set_clock_groups -asynchronous \
#     -group [get_clocks clk] \
#     -group [get_clocks clk2]

# --- Clock and reset ports (no IO delay) ---
set ports_no_delay [get_ports {clk rst_n}]

# --- Data port IO delays ---
set data_inputs [remove_from_collection [all_inputs] $ports_no_delay]
if {[sizeof_collection $data_inputs] > 0} {
    set_input_delay  0.2 -clock clk $data_inputs
}
if {[sizeof_collection [all_outputs]] > 0} {
    set_output_delay 0.2 -clock clk [all_outputs]
}

# --- Default drive and load ---
# set_drive 0 = ideal driver; adjust to real IO-cell specs.
set_drive 0    [all_inputs]
set_load  0.05 [all_outputs]

# --- Timing exceptions (uncomment as needed) ---
# set_false_path -from [get_ports rst_n]
# set_multicycle_path 2 -setup -from [get_cells u_cfg_reg]
