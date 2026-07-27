# tests/unit/test_lintcdc_bootstrap.py
"""lintcdc bootstrap verb — deploy-into-workdir behavior.

Two layers: in-process unit tests of the inference helpers (BP3 — byte-for-byte the
synthesis helpers), and subprocess "mirror" tests of full deploy behavior (BP2/BP4-BP11)
that run the real shipped skill with cwd set to a tmp design-tree root and build the
upstream asic/<module>/... references under it. The bootstrap anchors the design tree
on the CWD (matching kernel.py and the stage-subagent contract), independent of where
the skill code lives. Neither verb shells out to any Tier-2 script — bootstrap is a
pure deploy.

`_make_tree` pre-populates workdir/inputs.json (rtl/rtl_doc/sgdc_seed keys) the way
kernel.py dispatch injects it at dispatch time, and (when given `carried_sgdc` /
`carried_waiver`) pre-places files directly into workdir/scripts/ the way kernel.py's
carry_self does before this verb runs — bootstrap reads upstream locations from
inputs.json and carried files from the workdir itself, instead of self-navigating
tree_root/asic/<module>/Design/lint-cdc/scripts/... ."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN = REPO_ROOT / "skills" / "lint-cdc" / "scripts" / "lintcdc" / "__main__.py"
sys.path.insert(0, str(REPO_ROOT / "skills" / "lint-cdc" / "scripts"))
from lintcdc import bootstrap  # noqa: E402


# ── BP3: inference helpers (in-process, precise — copied from synthesis) ───────
def test_infer_top_from_readme_top_module_line(tmp_path):
    (tmp_path / "README.md").write_text("**Top module**: my_top\n\nbody\n")
    assert bootstrap.infer_top_from_readme(tmp_path) == "my_top"


def test_infer_top_from_readme_first_match_wins(tmp_path):
    (tmp_path / "README.md").write_text(
        "**Top module**: real_top\n\n- sync_cell top_sync added\n"
    )
    assert bootstrap.infer_top_from_readme(tmp_path) == "real_top"


def test_infer_top_from_readme_skips_table_rows(tmp_path):
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
    # chained .v/.sv/.vh strip, no break (a name ending '.sv.v' loses both).
    (tmp_path / "filelist.txt").write_text("foo.sv.v\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "foo"


def test_infer_top_from_filelist_none_when_absent(tmp_path):
    assert bootstrap.infer_top_from_filelist(tmp_path) is None


# ── BP2/BP4-BP11: full deploy (subprocess mirror) ─────────────────────────────
def _rtl_dir(workdir: Path) -> Path:
    """The rtl-design dir for a workdir built by _make_tree (.../Design/lint-cdc/runs/N)."""
    return workdir.parents[3] / "Design" / "rtl-design"


def _make_tree(
    tmp_path,
    *,
    top="dut",
    filelist="rtl/dut.v\n",
    readme=None,
    carried_sgdc=None,
    carried_waiver=None,
    cold=None,
    sdc=None,
):
    """Build the upstream asic/<module>/... refs under a tmp design-tree root, and
    pre-populate workdir/inputs.json (rtl/rtl_doc/sgdc_seed keys) the way kernel.py
    dispatch injects it. `carried_sgdc` / `carried_waiver`, when given, pre-place
    scripts/constraints.sgdc / scripts/waiver.tcl directly INTO the workdir — the way
    kernel.py's carry_self does before this verb runs.
    Returns (module, workdir, main). Deploy tests run `main` (the real shipped skill)
    with cwd=tmp_path, so the bootstrap anchors the design tree on the CWD."""
    m = "M"
    base = tmp_path / "asic" / m
    rtl = base / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    if filelist is not None:
        (rtl / "filelist.txt").write_text(filelist)
    if readme is not None:
        (rtl / "README.md").write_text(readme)
    spec_root = base / "Design" / "specification"
    if cold is not None or sdc is not None:
        spec_con = spec_root / "constraints"
        spec_con.mkdir(parents=True)
        if cold is not None:
            (spec_con / f"{top}.sgdc").write_text(cold)
        if sdc is not None:
            (spec_con / f"{top}.sdc").write_text(sdc)
    workdir = base / "Design" / "lint-cdc" / "runs" / "1"
    workdir.mkdir(parents=True)
    if carried_sgdc is not None or carried_waiver is not None:
        ws = workdir / "scripts"
        ws.mkdir(parents=True)
        if carried_sgdc is not None:
            (ws / "constraints.sgdc").write_text(carried_sgdc)
        if carried_waiver is not None:
            (ws / "waiver.tcl").write_text(carried_waiver)
    (workdir / "inputs.json").write_text(
        json.dumps({"rtl": str(rtl), "rtl_doc": str(rtl), "sgdc_seed": str(spec_root)})
    )
    return m, workdir, _MAIN


def _run(workdir, main, extra=None, cwd=None):
    if cwd is None:
        # The bootstrap anchors the design tree on the CWD; the tree root is the
        # prefix of the (absolute) workdir up to the 'asic/' component.
        parts = Path(workdir).parts
        cwd = Path(*parts[: parts.index("asic")])
    cmd = [
        "python3",
        str(main),
        "bootstrap",
        "--workdir",
        str(workdir),
    ]
    if extra:
        cmd += extra
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def test_deploys_and_substitutes_template_branch(tmp_path):
    # No warm/cold seed -> template branch: env.sh MY_TOP -> top, and the copytree'd
    # template constraints.sgdc IS MY_TOP-substituted.
    m, workdir, main = _make_tree(tmp_path)
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert (workdir / "Makefile").is_file()
    env_sh = (workdir / "env.sh").read_text()
    assert "MY_TOP" not in env_sh
    assert 'export TOP="${TOP:-dut}"' in env_sh
    con = (workdir / "scripts" / "constraints.sgdc").read_text()
    assert (
        "MY_TOP" not in con and "current_design dut" in con
    )  # template branch subs it


def test_carried_sgdc_used_and_not_resubstituted(tmp_path):
    # carried SGDC (pre-placed in workdir by carry_self) -> left alone, NOT MY_TOP-substituted.
    m, workdir, main = _make_tree(
        tmp_path,
        carried_sgdc="# SENTINEL carried sgdc\ncurrent_design dut\nquasi_static -name x\n",
    )
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert "SENTINEL carried" in (workdir / "scripts" / "constraints.sgdc").read_text()
    assert "carried scripts/constraints.sgdc" in r.stdout
    assert "MY_TOP" not in (workdir / "env.sh").read_text()


def test_carried_waiver_survives_template_deploy(tmp_path):
    # Pre-place a carried scripts/waiver.tcl (as kernel.py's carry_self would, BEFORE
    # this verb runs), then deploy: the no-clobber template deploy must NOT clobber it.
    m, workdir, main = _make_tree(tmp_path, carried_waiver="HUMAN AUDITED")
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert (workdir / "scripts" / "waiver.tcl").read_text() == "HUMAN AUDITED"


def test_no_carried_waiver_keeps_substituted_template(tmp_path):
    # No carried waiver -> the no-clobber-deployed template waiver.tcl stays, MY_TOP-substituted.
    m, workdir, main = _make_tree(tmp_path)
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    tpl = (workdir / "scripts" / "waiver.tcl").read_text()
    assert "MY_TOP" not in tpl


def test_cold_seed_used(tmp_path):
    # no carried sgdc, but spec <top>.sgdc present -> cold seed copied verbatim.
    m, workdir, main = _make_tree(
        tmp_path, cold="# SENTINEL cold sgdc\ncurrent_design dut\n"
    )
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert "SENTINEL cold" in (workdir / "scripts" / "constraints.sgdc").read_text()
    assert "cold-start" in r.stdout


def test_readme_inference_wins_over_filelist(tmp_path):
    m, workdir, main = _make_tree(
        tmp_path, readme="**Top module**: inferred_top\n", filelist="other.v\n"
    )
    r = _run(workdir, main)  # no --top
    assert r.returncode == 0, r.stderr
    assert 'export TOP="${TOP:-inferred_top}"' in (workdir / "env.sh").read_text()


def test_infer_from_filelist_when_top_omitted(tmp_path):
    # No --top, no README: TOP inferred from filelist first entry ('dut').
    m, workdir, main = _make_tree(tmp_path)  # filelist -> rtl/dut.v
    r = _run(workdir, main)  # no --top
    assert r.returncode == 0, r.stderr
    assert 'export TOP="${TOP:-dut}"' in (workdir / "env.sh").read_text()


def test_filelist_synced_and_rebased(tmp_path):
    # rtl-design/filelist.txt -> scripts/filelist.txt with the +incdir + re-anchored
    # ABSOLUTE paths. Skip set is {#, blank} ONLY: a comment is dropped, real .v lines
    # are re-anchored.
    m, workdir, main = _make_tree(
        tmp_path, filelist="# a comment\nrtl/dut.v\nrtl/sub/u.sv\n"
    )
    rtl_root = _rtl_dir(workdir)
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    gen = (workdir / "scripts" / "filelist.txt").read_text()
    assert f"+incdir+{rtl_root}" in gen
    assert f"{rtl_root}/rtl/dut.v" in gen
    assert f"{rtl_root}/rtl/sub/u.sv" in gen
    assert "../../../rtl-design" not in gen  # no relpath climb
    assert "a comment" not in gen  # comment skipped
    assert "bootstrap_lint_cdc" not in gen  # generated header names no retired .sh


def test_filelist_reanchors_to_absolute_rtl(tmp_path):
    # BP13: bootstrap reads the upstream rtl-design location from the injected
    # inputs.json "rtl" key — not by self-navigating tree_root/asic/<module>/....
    # scripts/filelist.txt must bake the ABSOLUTE rtl root, never a relative climb.
    m, workdir, main = _make_tree(tmp_path, filelist="rtl/dut.v\n")
    rtl_root = _rtl_dir(workdir)
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    src = (workdir / "scripts" / "filelist.txt").read_text()
    assert str(rtl_root) in src
    assert "../../../rtl-design" not in src


def test_empty_filelist_fail_closed(tmp_path):
    # filelist with only comments/blanks -> 0 usable entries -> exit 1.
    m, workdir, main = _make_tree(tmp_path, filelist="# only a comment\n\n")
    # --top given so we pass inference and reach the filelist sync.
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 1
    assert "no usable RTL entries" in r.stderr


def test_no_rtl_filelist_keeps_template_filelist(tmp_path):
    # rtl-design/filelist.txt absent -> sync is a no-op; the deployed regenerated-
    # placeholder template filelist.txt stays untouched (no MY_TOP, no relpath climb).
    m, workdir, main = _make_tree(tmp_path, filelist=None)
    r = _run(workdir, main, extra=["--top", "dut"])  # --top: no filelist to infer from
    assert r.returncode == 0, r.stderr
    gen = (workdir / "scripts" / "filelist.txt").read_text()
    assert "regenerated by bootstrap" in gen
    assert "../../../rtl-design" not in gen and "MY_TOP" not in gen


def test_cant_infer_top_fail_closed(tmp_path):
    # No --top, no README, filelist has no usable RTL entry -> inference None -> exit 1.
    m, workdir, main = _make_tree(tmp_path, filelist="+incdir+x\n", readme=None)
    r = _run(workdir, main)  # no --top
    assert r.returncode == 1
    assert "cannot infer top" in r.stderr


def test_already_deployed_guard(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    assert _run(workdir, main, extra=["--top", "dut"]).returncode == 0
    r2 = _run(workdir, main, extra=["--top", "dut"])
    assert r2.returncode == 1
    assert "already deployed" in r2.stderr


def test_missing_template_dir_fail_closed(tmp_path):
    # Run a skill COPY whose templates/ has been removed -> fail-closed before any
    # mutation. The design tree itself is valid under the CWD.
    m, workdir, _ = _make_tree(tmp_path)
    skill_copy = tmp_path / "skills" / "lint-cdc"
    shutil.copytree(REPO_ROOT / "skills" / "lint-cdc", skill_copy)
    shutil.rmtree(skill_copy / "templates")
    main = skill_copy / "scripts" / "lintcdc" / "__main__.py"
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 1
    assert "missing template directory" in r.stderr
    assert not (workdir / "Makefile").exists()  # fail-closed before any mutation


def test_period_mismatch_warns_not_fails(tmp_path):
    # cold sgdc period 10 vs sdc period 20 -> WARNING on stderr, exit STILL 0.
    m, workdir, main = _make_tree(
        tmp_path,
        cold="current_design dut\nclock -name clk -period 10\n",
        sdc="create_clock -period 20 [get_ports clk]\n",
    )
    r = _run(workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert "WARNING" in r.stderr and "periods disagree" in r.stderr


def test_relative_workdir_with_trailing_slash(tmp_path):
    # BP5: a relative --workdir resolves against the CWD (the design-tree root), and
    # the trailing slash is dropped before deploy.
    m, workdir, main = _make_tree(tmp_path)
    proc = subprocess.run(
        [
            "python3",
            str(main),
            "bootstrap",
            "--workdir",
            "asic/M/Design/lint-cdc/runs/1/",  # relative + trailing slash
            "--top",
            "dut",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (workdir / "Makefile").is_file()  # resolved to the absolute location
    assert (workdir / "env.sh").is_file()
