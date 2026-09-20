#!/usr/bin/env python3
"""Live VCS/URG and DC/PrimeTime probes for scope, missing metrics and numeric timing.

Run with the site's EDA environment; --workdir must be visible to the tools.
Raw reports and stage results remain there. No experiment inputs are modified.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/simulation/scripts"))
from sim._gate import coverage_gate  # noqa: E402


def run(argv, wd, log, timeout=240):
    with (wd / log).open("w") as f:
        result = subprocess.run(
            argv, cwd=wd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout
        )
    text = (wd / log).read_text(errors="replace")
    if result.returncode or re.search(r"^Error:", text, re.M):
        raise RuntimeError(f"{argv[0]} failed: {wd / log}")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def coverage(BASE):
    uvm = Path(os.environ["UVM_HOME"])
    write(
        BASE / "hierarchy/design.sv",
        r"""
    `timescale 1ns/1ps
    module leaf(input clk,reset,enable,mode,input [3:0] data,output reg [3:0] q);
    reg [1:0] state; localparam IDLE=0,A=1,B=2,C=3;
    always @(posedge clk) begin
     if(reset) begin state<=IDLE; q<=0; end
     else case(state)
     IDLE: if(enable) begin state<=A; q<=data; end
     A: begin if(mode) begin state<=B; q<=q+1; end else state<=C; end
     B: begin if(enable && mode) q<=data; state<=C; end
     C: state<=IDLE;
     endcase
    end
    endmodule
    module wrapper(input clk,reset,enable,mode,input [3:0] data,output [3:0] q);
    leaf child(clk,reset,enable,mode,data,q);
    endmodule
    module probe_tb_top;
    import uvm_pkg::*;
    reg clk=0, reset=1, enable=0, mode=0; reg [3:0] data=0;
    wire [3:0] q,peer_q;
    wrapper u_dut(clk,reset,enable,mode,data,q);
    wrapper peer(clk,reset,1'b1,mode,data,peer_q);
    always #5 clk=~clk;
    integer i;
    initial begin
     repeat(2) @(negedge clk); reset=0;
     for(i=0;i<160;i=i+1) begin
       @(negedge clk); data=i; mode=i[2]; enable=$test$plusargs("DENSE");
     end
     @(negedge clk);
     if(!enable && q!==0) $fatal(1,"idle output changed");
     uvm_report_info("PROBE", "COVERAGE_PROBE_PASS");
     $finish;
    end
    endmodule
    """,
    )
    write(
        BASE / "flat/design.sv",
        r"""
    `timescale 1ns/1ps
    module comb(input [3:0] a,b,output [3:0] q); assign q=a^b; endmodule
    module flat_tb_top;
    reg [3:0] a=0,b=0;wire [3:0] q;integer i;
    comb u_dut(a,b,q);
    initial begin
     for(i=0;i<32;i=i+1) begin a=i; b=i>>1;#10; if(q!==(a^b)) $fatal(1,"xor");end
     $display("COMB_PROBE_PASS");$finish;
    end
    endmodule
    """,
    )
    for case, top in [("hierarchy", "probe_tb_top"), ("flat", "flat_tb_top")]:
        wd = BASE / case
        args = [
            "vcs",
            "-full64",
            "-sverilog",
            "-timescale=1ns/1ps",
            "-cm",
            "line+cond+branch+tgl+fsm",
            "-cm_cond",
            "allops+event+anywidth",
            "-cm_dir",
            "elab.vdb",
            "-o",
            "simv",
            "-top",
            top,
        ]
        if case == "hierarchy":
            args += [
                "+incdir+" + str(uvm / "src"),
                str(uvm / "src/uvm_pkg.sv"),
                str(uvm / "src/dpi/uvm_dpi.cc"),
                "-CFLAGS",
                "-DVCS",
            ]
        run(args + ["design.sv"], wd, "compile.log")
        for variant in ["sparse", "dense"] if case == "hierarchy" else ["plain"]:
            run(
                [
                    "./simv",
                    "-cm",
                    "line+cond+branch+tgl+fsm",
                    "-cm_dir",
                    variant + ".vdb",
                ]
                + (["+DENSE"] if variant == "dense" else []),
                wd,
                variant + ".log",
            )
            run(
                [
                    "urg",
                    "-dir",
                    "elab.vdb",
                    "-dir",
                    variant + ".vdb",
                    "-report",
                    variant,
                    "-format",
                    "text",
                ],
                wd,
                variant + "-urg.log",
            )
            run(
                [
                    sys.executable,
                    str(
                        ROOT
                        / "skills/simulation/templates/infra/scripts/parse_coverage.py"
                    ),
                    "--cov-dir",
                    variant,
                    "--out",
                    variant + ".json",
                ],
                wd,
                variant + "-parse.log",
            )
        print("COVERAGE", case, "complete", flush=True)

    for case, variants, dut in [
        ("hierarchy", ["sparse", "dense"], "probe_tb_top.u_dut"),
        ("flat", ["plain"], "flat_tb_top.u_dut"),
    ]:
        for variant in variants:
            cov = json.loads((BASE / case / (variant + ".json")).read_text())
            rows = [
                {
                    "id": "TGL",
                    "target": {"dim": "coverage_toggle", "op": ">", "value": 90},
                }
            ]
            errors, verdict = coverage_gate(cov, rows, dut)
            assert verdict[0]["met"] == (variant != "sparse"), (errors, verdict)
            if case == "flat":
                rows[0]["target"]["dim"] = "coverage_fsm"
                errors, verdict = coverage_gate(cov, rows, dut)
                assert errors and not verdict[0]["met"] and verdict[0]["actual"] is None
            write(
                BASE / case / (variant + "-verdict.json"), json.dumps(verdict, indent=2)
            )


def timing(BASE):
    wd = BASE / "timing"
    wd.mkdir(exist_ok=True)
    write(
        wd / "pipe.v",
        "module pipe(input clk,input [15:0] a,b,output reg [15:0] q);always @(posedge clk) q<=a+b;endmodule\n",
    )
    write(
        wd / "synth.tcl",
        r"""
    set target_library [list $env(LIB_DB)]
    set link_library "* $env(LIB_DB)"
    define_design_lib WORK -path ./work
    analyze -format verilog pipe.v
    elaborate pipe
    current_design pipe
    link
    set_wire_load_mode top
    create_clock -name clk -period 10 [get_ports clk]
    set_input_delay 1 -clock clk [remove_from_collection [all_inputs] [get_ports clk]]
    set_output_delay 1 -max -clock clk [all_outputs]
    set_output_delay 0 -min -clock clk [all_outputs]
    compile_ultra
    write -format verilog -hierarchy -output pipe_syn.v
    write_sdc pipe_syn.sdc
    report_qor
    exit
    """,
    )
    run(["dc_shell", "-f", "synth.tcl"], wd, "synthesis.log")
    assert (wd / "pipe_syn.v").stat().st_size > 0
    for case, period in [
        ("met", 10),
        ("setup_violation", 0.01),
        ("hold_violation", 10),
        ("rounded_zero_violation", 10),
    ]:
        d = wd / case
        d.mkdir(exist_ok=True)
        write(
            d / "run.tcl",
            f"""
    set link_library "* $::env(LIB_DB)"
    set report_default_significant_digits 4
    read_verilog ../pipe_syn.v
    link_design pipe
    read_sdc ../pipe_syn.sdc
    create_clock -name clk -period {period} [get_ports clk]
    """
            + (
                "set_clock_uncertainty -hold 5 [get_clocks clk]\n"
                if case == "hold_violation"
                else ""
            )
            + (
                "set report_default_significant_digits 2\n"
                "set_clock_uncertainty -hold [expr {[get_attribute "
                "[get_timing_paths -delay_type min -max_paths 1] slack] + 0.001}] "
                "[get_clocks clk]\n"
                if case == "rounded_zero_violation"
                else ""
            )
            + r"""
    redirect timing-report.txt {
     report_timing -delay max
     report_timing -delay min
     check_timing
     report_analysis_coverage
    }
    exit
    """,
        )
        run(["pt_shell", "-f", "run.tcl"], d, "pt.log")
        print("TIMING", case, "complete", flush=True)

    for case, expected in [
        ("met", "pass"),
        ("setup_violation", "fail"),
        ("hold_violation", "fail"),
        ("rounded_zero_violation", "fail"),
    ]:
        d = wd / case
        write(
            d / "requirements.json",
            json.dumps(
                [
                    {
                        "id": "T",
                        "judge": "timing-analysis",
                        "verbatim": "setup and hold slack >= 0 ns",
                        "target": {"dim": "timing_slack_ns", "op": ">=", "value": 0},
                    }
                ]
            ),
        )
        write(d / "dispatch.json", json.dumps({"inputs": {"requirements": str(d)}}))
        run(
            [
                sys.executable,
                str(ROOT / "skills/timing-analysis/scripts/timing/__main__.py"),
                "finalize",
                "--workdir",
                str(d),
            ],
            d,
            "finalize.log",
        )
        result = json.loads((d / "result.json").read_text())
        assert result["status"] == expected, result
        assert result["stage_specific"]["requirements"][0]["met"] == (
            expected == "pass"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--only", choices=["coverage", "timing"])
    args = parser.parse_args()
    base = args.workdir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    if args.only != "timing":
        coverage(base)
    if args.only != "coverage":
        timing(base)
    print("All live EDA assertions passed.")


if __name__ == "__main__":
    main()
