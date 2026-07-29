# tests/unit/test_synthesis_bootstrap.py
"""synthesis bootstrap — deploy-into-workdir behavior.

Two layers: in-process unit tests of the inference helpers (BP1/BP2 — the
byte-stable README-grep coupling locked from the other side by
test_rtl_assemble.py), and subprocess "mirror" tests of full deploy behavior
(BP3-BP11) that run the real shipped skill with cwd set to a tmp design-tree
root. The bootstrap anchors the design tree on the CWD (matching kernel.py and
the stage-subagent contract), independent of where the skill code lives.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
sys.path.insert(0, str(REPO_ROOT / "skills" / "synthesis" / "scripts"))


# ── BP1/BP2: inference helpers (in-process, precise) ──────────────────────────
def _mirror(tmp_path):
    """Build the upstream asic/M/... refs under a tmp design-tree root; return
    (skill_dir, rtl_dir, workdir). skill_dir is the real shipped skill — deploy
    tests run it with cwd=tmp_path, so the bootstrap anchors the tree on the CWD.

    Pre-populates workdir/inputs.json (rtl/sdc/ppa/manifest keys) the way kernel.py dispatch
    injects it at dispatch time — bootstrap now reads upstream locations from
    inputs.json instead of self-navigating tree_root/asic/<module>/Design/... ."""
    skill_dst = REPO_ROOT / "skills" / "synthesis"
    rtl = tmp_path / "asic" / "M" / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    spec = tmp_path / "asic" / "M" / "Design" / "specification"
    workdir = tmp_path / "asic" / "M" / "Design" / "synthesis" / "runs" / "1"
    workdir.mkdir(parents=True)
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "manifest.json").write_text(json.dumps({"module": "M_top", "children": []}))
    # The SDC source of truth is REQUIRED (bootstrap fails closed without it); specification
    # always emits it, so the fixture does too. test_missing_spec_sdc_fails_closed removes it.
    con = spec / "constraints"
    con.mkdir(parents=True, exist_ok=True)
    for t_ in ("top", "M_top", "a"):
        (con / f"{t_}.sdc").write_text(f"# spec sdc for {t_}\ncreate_clock x\n")
    (workdir / "inputs.json").write_text(
        json.dumps(
            {"rtl": str(rtl), "sdc": str(spec), "ppa": str(spec), "manifest": str(spec)}
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
        json.dumps({"c": {"files": ["top.v"], "incdirs": ["sub/inc"]}})
    )
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    gen = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert "set_app_var search_path" in gen
    assert "sub/inc" in gen
    assert "+incdir+" not in gen
    assert "analyze -format sverilog -define SYNTHESIS" in gen
    assert "top.v" in gen


def test_define_and_dashf_still_skipped(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    gen = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert "FOO" not in gen
    assert "other.f" not in gen
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
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["a.v", "b.v"]}}))
    proc = _run(skill_dst, workdir, "--top", "a")
    assert proc.returncode == 0, proc.stderr
    gen = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert "proc _analyze_or_die" in gen
    assert "exit 1" in gen
    calls = [ln for ln in gen.splitlines() if ln.startswith("_analyze_or_die {")]
    assert len(calls) == 2, calls
    ungated = [ln for ln in gen.splitlines() if ln.startswith("analyze ")]
    assert ungated == [], ungated


def test_missing_spec_sdc_fails_closed(tmp_path):
    # The template constraints.sdc is a COMPLETE runnable SDC naming clock `clk` at 10 ns and
    # ports clk/rst_n. Deploying it on a design with different port names leaves the run
    # effectively unconstrained, and dc_shell then reports a large positive slack — a PASSING
    # PPA verdict from constraints nobody wrote. Refuse instead.
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
    (tmp_path / "asic/M/Design/specification/constraints/top.sdc").unlink()
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode != 0
    assert "SDC source of truth not found" in proc.stderr
    # and nothing was deployed, so the already-deployed guard cannot block the retry
    assert not (workdir / "Makefile").exists()
    assert not (workdir / "constraints.sdc").exists()
    assert _run(skill_dst, workdir, "--top", "M_top").returncode == 0  # retry works


def test_happy_path_substitutes_my_top(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    env_sh = (workdir / "env.sh").read_text()
    assert "MY_TOP" not in env_sh and "top" in env_sh
    cfg = (workdir / "scripts" / "config.tcl").read_text()
    assert 'set ::env(TOP)    "top"' in cfg
    assert "set ::env(LIB_DB)" in cfg  # parseable by result.read_lib_db
    assert "MY_RTL_DIR" not in (workdir / "scripts" / "dc_run.tcl").read_text()


def test_sdc_source_of_truth_copied(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
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
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": []}}))
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 1
    assert "lists no RTL files" in proc.stderr


def test_missing_filelist_fail_closed(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)  # rtl dir exists, no rtl-files.json
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 1
    assert "missing" in proc.stderr and "rtl-files.json" in proc.stderr


def test_top_read_from_manifest(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(
        json.dumps({"c": {"files": ["some_other_name.v"]}})
    )
    assert _run(skill_dst, workdir).returncode == 0  # no --top
    # manifest.module wins; the filelist basename is not consulted at all
    assert "M_top" in (workdir / "env.sh").read_text()


def test_cant_read_top_fail_closed(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
    spec = tmp_path / "asic" / "M" / "Design" / "specification"
    (spec / "manifest.json").unlink()
    proc = _run(skill_dst, workdir)  # no --top
    assert proc.returncode == 1
    assert "cannot read top" in proc.stderr


def test_already_deployed_guard(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
    assert _run(skill_dst, workdir, "--top", "top").returncode == 0
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 1
    assert "already deployed" in proc.stderr


def test_rtl_load_skips_double_slash_comment(tmp_path):
    # BP2/BP11 asymmetry (the rtl_load side): rtl_load generation DOES skip '//'
    # comments (skip set {#, //, blank, +/-}), so a '//skip_me.v' line is not
    # emitted as analyze. (Inference does NOT skip '//' — see the in-process test.)
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
    proc = _run(
        skill_dst, workdir, "--top", "top"
    )  # --top given so inference is bypassed
    assert proc.returncode == 0, proc.stderr
    gen = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert "skip_me" not in gen
    assert "top.v" in gen


def test_relative_workdir_with_trailing_slash(tmp_path):
    # BP12: a relative --workdir resolves against the CWD (the design-tree root), and
    # a trailing slash is stripped before path resolution.
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
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
    assert (workdir / "Makefile").is_file()  # resolved to the absolute location
    assert (workdir / "scripts" / "config.tcl").is_file()


def test_bootstrap_reanchors_rtl_load_to_absolute_from_inputs_json(tmp_path):
    # BP13: bootstrap reads the upstream rtl-design location from the injected
    # inputs.json "rtl" key — not by self-navigating tree_root/asic/<module>/....
    # rtl_load.tcl must bake the ABSOLUTE rtl root, never a relative "../.." climb.
    skill_dst, rtl_root, workdir = _mirror(tmp_path)
    (rtl_root / "rtl-files.json").write_text(json.dumps({"c": {"files": ["top.v"]}}))
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    tcl = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert str(rtl_root) in tcl
    assert "../../../rtl-design" not in tcl and "relpath" not in tcl
