# Generic single-clock timing constraints (DC synthesis + reused for STA).
# Replace clk/rst_n and the 10ns period with your design's real ports/frequency.
create_clock -name clk -period 10.0 [get_ports clk]
set_clock_uncertainty -setup 0.2 [all_clocks]
set_clock_uncertainty -hold  0.0 [all_clocks]

set ports_no_delay [get_ports {clk rst_n}]
set data_inputs [remove_from_collection [all_inputs] $ports_no_delay]
if {[sizeof_collection $data_inputs] > 0} { set_input_delay 0.2 -clock clk $data_inputs }
if {[sizeof_collection [all_outputs]] > 0} { set_output_delay 0.2 -clock clk [all_outputs] }
set_drive 0    [all_inputs]
set_load  0.05 [all_outputs]
