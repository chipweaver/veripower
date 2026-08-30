// tb_sources.f — sources this bench compiles that the scaffold does not generate.
//
// One path per line, relative to the run directory; `//` starts a comment. filelist.f pulls
// this in and is re-derived from the plan every round, so anything written there is lost —
// this file is not, which is why it exists.
//
// What belongs here is what the scaffold cannot know about: the C or C++ implementing a DPI
// import the testbench declares. A reference model written that way is compiled from here.
//
// tb/uvm/refmodel/{{MODULE}}_ref.c
