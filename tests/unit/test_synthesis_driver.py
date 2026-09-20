"""Execute the shipped Tcl against controlled tool responses, without a circuit or EDA license."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/synthesis/scripts"))
from synthesis.bootstrap import render_rtl_load_tcl  # noqa: E402


@pytest.mark.parametrize(
    "failure,requested_model,effective_model,expected",
    [
        ("", "none", "none", 0),
        ("analyze", "none", "none", 1),
        ("elaborate", "none", "none", 1),
        ("link", "none", "none", 1),
        ("check_design", "none", "none", 1),
        ("compile_ultra", "none", "none", 1),
        ("", "selected_model", "selected_model", 0),
        ("", "selected_model", "none", 1),
        ("", "none", "unwanted_model", 1),
    ],
)
def test_failed_tool_steps_cannot_publish_a_netlist(
    tmp_path, failure, requested_model, effective_model, expected
):
    tclsh = shutil.which("tclsh")
    if not tclsh:
        pytest.skip("Tcl interpreter required for driver execution")
    (tmp_path / "library.db").touch()
    (tmp_path / "source.sv").write_text(
        "opaque input to the controlled analyze command\n"
    )
    (tmp_path / "rtl-files.json").write_text(json.dumps({"files": ["source.sv"]}))
    (tmp_path / "rtl_load.tcl").write_text(render_rtl_load_tcl(tmp_path))
    (tmp_path / "config.tcl").write_text(
        f"set TOP dut\nset LIB_DB library.db\nset WIRE_LOAD_MODEL {requested_model}\n"
    )
    for name in ("constraints.sdc", "constraints.local.sdc"):
        (tmp_path / name).touch()
    shutil.copy2(
        ROOT / "skills/synthesis/templates/scripts/dc_run.tcl", tmp_path / "driver.tcl"
    )
    (tmp_path / "run.tcl").write_text(r"""
foreach command {analyze elaborate link compile_ultra} {
    proc $command {args} [string map [list COMMAND $command] {
        puts "CALL COMMAND"
        return [expr {$::env(FAILURE) ne "COMMAND"}]
    }]
}
foreach command {set_app_var define_design_lib current_design set_wire_load_mode change_names} {
    proc $command {args} {}
}
proc get_app_var {name} {return {}}
proc set_wire_load_model {args} {puts "MODEL $args"}
proc check_design {redirect destination} {
    set stream [open $destination w]
    if {$::env(FAILURE) eq "check_design"} {puts $stream "Error: invalid design"}
    close $stream
}
proc report_area {args} {
    set stream [open [lindex $args end] w]
    puts $stream [expr {$::env(EFFECTIVE_MODEL) eq "none" ? "No wire load specified" : "Wire load model selected"}]
    close $stream
}
foreach command {report_qor report_power} {
    proc $command {redirect destination} {close [open $destination w]}
}
proc redirect {destination body} {close [open $destination w]}
foreach command {write write_sdc write_sdf} {
    proc $command {args} {close [open [lindex $args end] w]}
}
proc quit {} {exit 0}
source driver.tcl
""")
    process = subprocess.run(
        [tclsh, "run.tcl"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "FAILURE": failure, "EFFECTIVE_MODEL": effective_model},
    )
    assert process.returncode == expected, process.stderr
    assert (tmp_path / "out/dut_syn.v").exists() == (expected == 0)
    if failure:
        steps = ["analyze", "elaborate", "link", "check_design", "compile_ultra"]
        for later in steps[steps.index(failure) + 1 :]:
            assert f"CALL {later}" not in process.stdout
    if expected == 0:
        assert "CALL compile_ultra" in process.stdout
    if requested_model != "none":
        assert f"MODEL -name {requested_model}" in process.stdout
