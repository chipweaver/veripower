// Reset generation for {{TOP}}'s bench — authored, and kept across rounds.
//
// `include`d inside {{TOP}}_tb_top, so `clk`, `rst_n` and every agent interface instance are
// in scope here. tb_top itself is re-derived from the plan every round; this file is not, so
// when the bench resets is yours to decide and survives a rework.
//
// The default is a power-on reset and nothing more. Add pulses when a check or a coverage
// item needs the design reset while it is running — a reset exit from a state the design
// only passes through is reachable no other way.

initial begin
  rst_n = 0;
  #20 rst_n = 1;
end
