# tests/unit/test_synthesis_bootstrap.py
"""synthesis bootstrap — deploy-into-workdir behavior.

Every test runs the real shipped skill as a subprocess with cwd set to a tmp
design-tree root, because the bootstrap anchors the design tree on the CWD
(matching kernel.py and the stage-subagent contract) rather than on where the
skill code lives — an in-process call would resolve against the test runner's cwd
and prove nothing about that.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
sys.path.insert(0, str(REPO_ROOT / "skills" / "synthesis" / "scripts"))


def _mirror(tmp_path):
    """Build the upstream asic/M/... refs under a tmp design-tree root; return
    (skill_dir, rtl_dir, workdir). skill_dir is the real shipped skill — deploy
    tests run it with cwd=tmp_path, so the bootstrap anchors the tree on the CWD.

    Pre-populates workdir/dispatch.json (rtl/sdc/ppa/manifest keys) the way kernel.py dispatch
    injects it, which is where bootstrap reads every upstream location from."""
    skill_dst = REPO_ROOT / "skills" / "synthesis"
    rtl = tmp_path / "asic" / "M" / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    spec = tmp_path / "asic" / "M" / "Design" / "specification"
    workdir = tmp_path / "asic" / "M" / "Design" / "synthesis" / "runs" / "1"
    workdir.mkdir(parents=True)
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "manifest.json").write_text(json.dumps({"module": "M_top"}))
    # The SDC source of truth is REQUIRED (bootstrap fails closed without it); specification
    # always emits it, so the fixture does too. test_missing_spec_sdc_fails_closed removes it.
    con = spec / "constraints"
    con.mkdir(parents=True, exist_ok=True)
    for t_ in ("top", "M_top", "a"):
        (con / f"{t_}.sdc").write_text(f"# spec sdc for {t_}\ncreate_clock x\n")
    (workdir / "dispatch.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "rtl": str(rtl),
                    "sdc": str(spec),
                    "requirements": str(spec),
                    "manifest": str(spec),
                }
            }
        )
    )
    return skill_dst, rtl, workdir


def _run(skill_dst, workdir, *extra):
    # The bootstrap anchors the design tree on the CWD; the tree root is the prefix
    # of the (absolute) workdir up to the 'asic/' component.
    parts = Path(workdir).parts
    cwd = Path(*parts[: parts.index("asic")])
    return subprocess.run(
        [
            "python3",
            str(skill_dst / "scripts" / "synthesis" / "__main__.py"),
            "bootstrap",
            "--workdir",
            str(workdir),
            *extra,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_incdir_becomes_search_path_entry(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(
        json.dumps({"files": ["top.v"], "incdirs": ["sub/inc"]})
    )
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    gen = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert "set_app_var search_path" in gen
    assert "sub/inc" in gen
    assert "+incdir+" not in gen
    assert "analyze -format sverilog -define SYNTHESIS" in gen
    assert "top.v" in gen


def test_rtl_load_gates_every_analyze(tmp_path):
    """Every generated analyze is gated, and no ungated one survives.

    An unchecked analyze failure is not benign: DC keeps going, the module ends up
    unresolved, and because DC reports an unresolved reference as a Warning rather
    than an Error, dc_run.tcl's check_design gate does not fire either — `compile`
    then succeeds and the stage reports a clean (and smaller) QoR for a design
    missing a whole module. The companion gates on elaborate / link live in
    tests/contracts/test_dc_run_gates.py.
    """
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["a.v", "b.v"]}))
    proc = _run(skill_dst, workdir, "--top", "a")
    assert proc.returncode == 0, proc.stderr
    gen = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert "proc _analyze_or_die" in gen
    assert "exit 1" in gen
    calls = [ln for ln in gen.splitlines() if ln.startswith("_analyze_or_die ")]
    assert len(calls) == 2, calls
    ungated = [ln for ln in gen.splitlines() if ln.startswith("analyze ")]
    assert ungated == [], ungated


def test_missing_spec_sdc_fails_closed(tmp_path):
    # There is deliberately no template SDC to fall back to. Any generic one would declare a
    # clock on port names this design may not have, `get_ports` would match nothing, and
    # dc_shell would report a large positive slack — a PASSING PPA verdict from constraints
    # nobody wrote. Refuse instead.
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    (tmp_path / "asic/M/Design/specification/constraints/top.sdc").unlink()
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode != 0
    assert "SDC source of truth not found" in proc.stderr
    # Invalid input leaves setup uninstalled, and corrected input permits a retry.
    assert not (workdir / "config.tcl").exists()
    assert not (workdir / "constraints.sdc").exists()
    assert _run(skill_dst, workdir, "--top", "M_top").returncode == 0  # retry works


def test_happy_path_substitutes_my_top(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    env_sh = (workdir / "config.tcl").read_text()
    assert "MY_TOP" not in env_sh and "top" in env_sh
    assert "MY_RTL_DIR" not in (workdir / "scripts" / "dc_run.tcl").read_text()


def test_sdc_source_of_truth_copied(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    spec_con = tmp_path / "asic" / "M" / "Design" / "specification" / "constraints"
    (spec_con / "top.sdc").write_text("# SENTINEL real sdc\ncreate_clock x\n")
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    con = (workdir / "constraints.sdc").read_text()
    assert (
        "SENTINEL" in con and "MY_TOP" not in con
    )  # copied verbatim, never substituted


def test_empty_filelist_fail_closed(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": []}))
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 1
    assert "lists no RTL files" in proc.stderr
    assert not (workdir / "config.tcl").exists()
    assert not (workdir / "scripts").exists()


def test_missing_filelist_fail_closed(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)  # rtl dir exists, no rtl-files.json
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 1
    assert "missing" in proc.stderr and "rtl-files.json" in proc.stderr
    assert not (workdir / "config.tcl").exists()
    # and the retry works once rtl-design has written the layout
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    assert _run(skill_dst, workdir, "--top", "top").returncode == 0


def test_top_read_from_manifest(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["some_other_name.v"]}))
    assert _run(skill_dst, workdir).returncode == 0  # no --top
    # manifest.module wins; the filelist basename is not consulted at all
    assert "M_top" in (workdir / "config.tcl").read_text()


def test_cant_read_top_fail_closed(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    spec = tmp_path / "asic" / "M" / "Design" / "specification"
    (spec / "manifest.json").unlink()
    proc = _run(skill_dst, workdir)  # no --top
    assert proc.returncode == 1
    assert "cannot read top" in proc.stderr


def test_bootstrap_preserves_authored_driver(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    assert _run(skill_dst, workdir, "--top", "top").returncode == 0
    driver = workdir / "scripts/dc_run.tcl"
    driver.write_text("# authored calculation with literal MY_RTL_DIR\n")
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0
    assert driver.read_text() == "# authored calculation with literal MY_RTL_DIR\n"


def test_relative_workdir_with_trailing_slash(tmp_path):
    # A relative --workdir resolves against the CWD (the design-tree root), and
    # a trailing slash is stripped before path resolution.
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    proc = subprocess.run(
        [
            "python3",
            str(skill_dst / "scripts" / "synthesis" / "__main__.py"),
            "bootstrap",
            "--workdir",
            "asic/M/Design/synthesis/runs/1/",  # relative + trailing slash
            "--top",
            "top",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (workdir / "config.tcl").is_file()  # resolved to the absolute location
    assert (workdir / "scripts" / "dc_run.tcl").is_file()


def test_bootstrap_reanchors_rtl_load_to_absolute_from_dispatch_json(tmp_path):
    # bootstrap reads the upstream rtl-design location from the injected
    # dispatch.json "rtl" key — not by self-navigating tree_root/asic/<module>/....
    # rtl_load.tcl must bake the ABSOLUTE rtl root, never a relative "../.." climb.
    skill_dst, rtl_root, workdir = _mirror(tmp_path)
    (rtl_root / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    tcl = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert str(rtl_root) in tcl
    assert "../../../rtl-design" not in tcl and "relpath" not in tcl


def test_tool_configuration_preserves_literal_values(tmp_path, monkeypatch):
    value = 'space $variable [error injected] "quotes" \\path'
    monkeypatch.setenv("LIB_DB", value)
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    assert _run(skill_dst, workdir, "--top", "top").returncode == 0
    (workdir / "probe.tcl").write_text("source config.tcl\nputs -nonewline $LIB_DB\n")
    seen = subprocess.run(
        ["tclsh", "probe.tcl"], cwd=workdir, capture_output=True, text=True
    )
    assert seen.returncode == 0 and seen.stdout == value


def test_seed_and_carried_local_remain_separate(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    (workdir / "constraints.local.sdc").write_text(
        "# LOCAL\nset_clock_uncertainty -setup 0.15 [get_clocks clk]\n"
    )
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    out = (workdir / "constraints.sdc").read_text()
    assert "spec sdc for top" in out and "# LOCAL" not in out
    assert (
        "set_clock_uncertainty -setup 0.15"
        in (workdir / "constraints.local.sdc").read_text()
    )


def test_a_corrected_seed_reaches_dc_without_the_stage_acting(tmp_path):
    """The defect this replaces: the seed was read once, on round 1, so a specification-side
    correction landed in a file the stage never opened again."""
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    (workdir / "constraints.local.sdc").write_text("# carried local, untouched\n")
    con = workdir.parents[2] / "specification" / "constraints"
    (con / "top.sdc").write_text("# spec sdc for top\ncreate_clock -period 4.0 x\n")
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    out = (workdir / "constraints.sdc").read_text()
    assert "create_clock -period 4.0" in out
    assert (
        workdir / "constraints.local.sdc"
    ).read_text() == "# carried local, untouched\n"


def test_driver_reads_local_edits_on_each_invocation(tmp_path):
    """Exercise the deployed Tcl entrypoint, stopping at the mapping command.

    Tool commands are stubbed here; real DC constraint observations run separately.
    """
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"files": ["top.v"]}))
    seed = workdir.parents[2] / "specification/constraints/top.sdc"
    seed.write_text("set audit_constraint seed\n")
    assert _run(skill_dst, workdir, "--top", "top").returncode == 0
    library = tmp_path / "test.db"
    library.touch()
    (workdir / "config.tcl").write_text(
        f'set TOP top\nset LIB_DB "{library}"\nset WIRE_LOAD_MODEL none\n'
    )
    (workdir / "probe.tcl").write_text(
        """proc set_app_var args {}
proc get_app_var args {return {}}
proc define_design_lib args {}
proc analyze args {return 1}
proc elaborate args {return 1}
proc current_design args {}
proc link args {return 1}
proc check_design args {close [open [lindex $args end] w]}
proc set_wire_load_mode args {}
proc compile_ultra {} {puts "observed=$::audit_constraint"; exit 0}
source scripts/dc_run.tcl
"""
    )
    local = workdir / "constraints.local.sdc"
    for value in ("first", "changed", None):
        local.write_text(f"set audit_constraint {value}\n" if value else "")
        seen = subprocess.run(
            ["tclsh", "probe.tcl"],
            cwd=workdir,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "TOP": "top",
                "LIB_DB": str(library),
                "WIRE_LOAD_MODEL": "none",
            },
        )
        assert seen.returncode == 0, seen.stderr
        assert f"observed={value or 'seed'}" in seen.stdout


def test_loader_preserves_source_and_include_paths(tmp_path):
    skill, rtl, wd = _mirror(tmp_path / 'project [literal] $var {x} "quoted"')
    source = "src/core [literal] $var {x}.v"
    include = "src/include [literal] $var {x}"
    (rtl / "rtl-files.json").write_text(
        json.dumps({"files": [source], "incdirs": [include]})
    )
    assert _run(skill, wd, "--top", "top").returncode == 0
    (wd / "probe.tcl").write_text(
        "proc get_app_var name {return {}}\n"
        'proc set_app_var {name paths} {foreach p $paths {puts "INCLUDE:$p"}}\n'
        'proc analyze args {puts "SOURCE:[lindex [lindex $args end] 0]"; return 1}\n'
        "source scripts/rtl_load.tcl\n"
    )
    p = subprocess.run(["tclsh", "probe.tcl"], cwd=wd, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == [
        f"INCLUDE:{rtl / include}",
        f"SOURCE:{rtl / source}",
    ]
