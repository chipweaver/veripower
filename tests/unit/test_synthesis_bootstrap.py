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
from synthesis import bootstrap  # noqa: E402


# ── BP1/BP2: inference helpers (in-process, precise) ──────────────────────────
def test_infer_top_from_readme_top_module_line(tmp_path):
    # The byte-stable line rtl-design emits + synth greps (test_rtl_assemble.py).
    (tmp_path / "README.md").write_text("**Top module**: my_top\n\nbody\n")
    assert bootstrap.infer_top_from_readme(tmp_path) == "my_top"


def test_infer_top_from_readme_first_match_wins(tmp_path):
    # head -1 semantics: the Top line is line 1; a later 'top'-bearing line
    # (e.g. a sync_cell annotation) must not win.
    (tmp_path / "README.md").write_text(
        "**Top module**: real_top\n\n- sync_cell top_sync added\n"
    )
    assert bootstrap.infer_top_from_readme(tmp_path) == "real_top"


def test_infer_top_from_readme_skips_table_rows(tmp_path):
    # A 'top' mention only inside a markdown table row → not inferred.
    (tmp_path / "README.md").write_text("| top | note |\n|---|---|\n| a | b |\n")
    assert bootstrap.infer_top_from_readme(tmp_path) is None


def test_infer_top_from_readme_none_when_absent(tmp_path):
    assert bootstrap.infer_top_from_readme(tmp_path) is None


def test_infer_top_from_filelist_basename(tmp_path):
    (tmp_path / "filelist.txt").write_text("rtl/foo.sv\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "foo"


def test_infer_top_from_filelist_skips_directives_and_comments(tmp_path):
    (tmp_path / "filelist.txt").write_text("# header\n+incdir+inc\ntop.v\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "top"


def test_infer_top_from_filelist_sequential_ext_strip(tmp_path):
    # chained .v/.sv/.vh strip, no break (a name ending '.sv.v' loses both):
    # foo.sv.v -> (strip .v) foo.sv -> (strip .sv) foo
    (tmp_path / "filelist.txt").write_text("foo.sv.v\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "foo"


def test_infer_top_from_filelist_does_not_skip_double_slash(tmp_path):
    # BP2 asymmetry: the inference skip set is {#, blank, +/-} — it does NOT skip
    # '//'. So a leading '//top.v' line IS the first entry: basename('//top.v')
    # -> 'top.v' -> 'top'. (rtl_load generation DOES skip '//' — see
    # test_rtl_load_skips_double_slash_comment below; the two skip sets differ.)
    (tmp_path / "filelist.txt").write_text("//top.v\nreal.v\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "top"


# ── BP3-BP11: full deploy (subprocess mirror) ─────────────────────────────────
def _mirror(tmp_path):
    """Build the upstream asic/M/... refs under a tmp design-tree root; return
    (skill_dir, rtl_dir, workdir). skill_dir is the real shipped skill — deploy
    tests run it with cwd=tmp_path, so the bootstrap anchors the tree on the CWD.

    Pre-populates workdir/inputs.json (rtl/sdc/ppa keys) the way kernel.py dispatch
    injects it at dispatch time — bootstrap now reads upstream locations from
    inputs.json instead of self-navigating tree_root/asic/<module>/Design/... ."""
    skill_dst = REPO_ROOT / "skills" / "synthesis"
    rtl = tmp_path / "asic" / "M" / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    spec = tmp_path / "asic" / "M" / "Design" / "specification"
    workdir = tmp_path / "asic" / "M" / "Design" / "synthesis" / "runs" / "1"
    workdir.mkdir(parents=True)
    (workdir / "inputs.json").write_text(
        json.dumps({"rtl": str(rtl), "sdc": str(spec), "ppa": str(spec)})
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
            "--module",
            "M",
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
    (rtl / "filelist.txt").write_text("+incdir+sub/inc\ntop.v\n")
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
    (rtl / "filelist.txt").write_text("+define+FOO=1\n-f other.f\ntop.v\n")
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    gen = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert "FOO" not in gen
    assert "other.f" not in gen
    assert "top.v" in gen


def test_happy_path_substitutes_my_top(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "filelist.txt").write_text("top.v\n")
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    # No spec SDC -> template branch; the placeholder must be announced (not silent).
    assert "PLACEHOLDER constraints.sdc" in proc.stdout
    env_sh = (workdir / "env.sh").read_text()
    assert "MY_TOP" not in env_sh and "top" in env_sh
    cfg = (workdir / "scripts" / "config.tcl").read_text()
    assert 'set ::env(TOP)    "top"' in cfg
    assert "set ::env(LIB_DB)" in cfg  # parseable by result.read_lib_db
    assert "MY_RTL_DIR" not in (workdir / "scripts" / "dc_run.tcl").read_text()


def test_readme_top_inference_wins_over_filelist(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "README.md").write_text("**Top module**: inferred_top\n")
    (rtl / "filelist.txt").write_text("other.v\n")
    proc = _run(skill_dst, workdir)  # no --top
    assert proc.returncode == 0, proc.stderr
    assert (
        'set ::env(TOP)    "inferred_top"'
        in (workdir / "scripts" / "config.tcl").read_text()
    )


def test_sdc_source_of_truth_copied(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "filelist.txt").write_text("top.v\n")
    spec_con = tmp_path / "asic" / "M" / "Design" / "specification" / "constraints"
    spec_con.mkdir(parents=True)
    (spec_con / "top.sdc").write_text("# SENTINEL real sdc\ncreate_clock x\n")
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    con = (workdir / "constraints.sdc").read_text()
    assert "SENTINEL" in con and "MY_TOP" not in con
    assert "PLACEHOLDER" not in proc.stdout  # spec-SDC branch must not warn


def test_empty_filelist_fail_closed(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "filelist.txt").write_text("# only a comment\n+incdir+x\n")
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 1
    assert "no usable RTL entries" in proc.stderr


def test_missing_filelist_fail_closed(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)  # rtl dir exists, no filelist.txt
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 1
    assert "missing" in proc.stderr and "filelist.txt" in proc.stderr


def test_cant_infer_top_fail_closed(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "filelist.txt").write_text("+incdir+x\n")  # no RTL, no README
    proc = _run(skill_dst, workdir)  # no --top
    assert proc.returncode == 1
    assert "cannot infer top" in proc.stderr


def test_already_deployed_guard(tmp_path):
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "filelist.txt").write_text("top.v\n")
    assert _run(skill_dst, workdir, "--top", "top").returncode == 0
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 1
    assert "already deployed" in proc.stderr


def test_rtl_load_skips_double_slash_comment(tmp_path):
    # BP2/BP11 asymmetry (the rtl_load side): rtl_load generation DOES skip '//'
    # comments (skip set {#, //, blank, +/-}), so a '//skip_me.v' line is not
    # emitted as analyze. (Inference does NOT skip '//' — see the in-process test.)
    skill_dst, rtl, workdir = _mirror(tmp_path)
    (rtl / "filelist.txt").write_text("//skip_me.v\ntop.v\n")
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
    (rtl / "filelist.txt").write_text("top.v\n")
    proc = subprocess.run(
        [
            "python3",
            str(skill_dst / "scripts" / "synthesis" / "__main__.py"),
            "bootstrap",
            "--module",
            "M",
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
    (rtl_root / "filelist.txt").write_text("top.v\n")
    proc = _run(skill_dst, workdir, "--top", "top")
    assert proc.returncode == 0, proc.stderr
    tcl = (workdir / "scripts" / "rtl_load.tcl").read_text()
    assert str(rtl_root) in tcl
    assert "../../../rtl-design" not in tcl and "relpath" not in tcl
