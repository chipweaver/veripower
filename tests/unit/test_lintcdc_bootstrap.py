# tests/unit/test_lintcdc_bootstrap.py
"""lintcdc bootstrap verb — deploy-into-workdir behavior.

Two layers: in-process unit tests of the inference helpers (BP3 — byte-for-byte the
synthesis helpers), and subprocess "mirror" tests of full deploy behavior (BP2/BP4-BP11)
that copy skills/lint-cdc into a tmp tree so the package's _REPO_ROOT (= _HERE.parents[4])
resolves to tmp_path, then build the upstream asic/<module>/... references under it.
Neither verb shells out to any Tier-2 script — bootstrap is a pure deploy.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
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
def _make_tree(
    tmp_path,
    *,
    top="dut",
    filelist="rtl/dut.v\n",
    readme=None,
    warm=None,
    cold=None,
    sdc=None,
):
    """Mirror skills/lint-cdc into tmp + build the upstream asic/<module>/... refs.
    Returns (module, workdir, main). The copied package's _HERE.parents[4] resolves
    _REPO_ROOT to tmp_path."""
    shutil.copytree(REPO_ROOT / "skills" / "lint-cdc", tmp_path / "skills" / "lint-cdc")
    m = "M"
    base = tmp_path / "asic" / m
    rtl = base / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    if filelist is not None:
        (rtl / "filelist.txt").write_text(filelist)
    if readme is not None:
        (rtl / "README.md").write_text(readme)
    if warm is not None:
        ws = base / "Design" / "lint-cdc" / "scripts"
        ws.mkdir(parents=True)
        (ws / "constraints.sgdc").write_text(warm)
    if cold is not None or sdc is not None:
        spec = base / "Design" / "specification" / "constraints"
        spec.mkdir(parents=True)
        if cold is not None:
            (spec / f"{top}.sgdc").write_text(cold)
        if sdc is not None:
            (spec / f"{top}.sdc").write_text(sdc)
    workdir = base / "Design" / "lint-cdc" / "runs" / "1"
    main = tmp_path / "skills" / "lint-cdc" / "scripts" / "lintcdc" / "__main__.py"
    return m, workdir, main


def _run(module, workdir, main, extra=None):
    cmd = [
        "python3",
        str(main),
        "bootstrap",
        "--module",
        module,
        "--workdir",
        str(workdir),
    ]
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True)


def test_deploys_and_substitutes_template_branch(tmp_path):
    # No warm/cold seed -> template branch: env.sh MY_TOP -> top, and the copytree'd
    # template constraints.sgdc IS MY_TOP-substituted.
    m, workdir, main = _make_tree(tmp_path)
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert (workdir / "Makefile").is_file()
    env_sh = (workdir / "env.sh").read_text()
    assert "MY_TOP" not in env_sh
    assert 'export TOP="${TOP:-dut}"' in env_sh
    con = (workdir / "scripts" / "constraints.sgdc").read_text()
    assert (
        "MY_TOP" not in con and "current_design dut" in con
    )  # template branch subs it


def test_warm_seed_used_and_not_resubstituted(tmp_path):
    # warm SGDC present -> copied verbatim (already bound, NOT MY_TOP-substituted).
    m, workdir, main = _make_tree(
        tmp_path,
        warm="# SENTINEL warm sgdc\ncurrent_design dut\nquasi_static -name x\n",
    )
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert "SENTINEL warm" in (workdir / "scripts" / "constraints.sgdc").read_text()
    assert "warm-start" in r.stdout
    assert "MY_TOP" not in (workdir / "env.sh").read_text()


def test_cold_seed_used(tmp_path):
    # no warm, but spec <top>.sgdc present -> cold seed copied verbatim.
    m, workdir, main = _make_tree(
        tmp_path, cold="# SENTINEL cold sgdc\ncurrent_design dut\n"
    )
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert "SENTINEL cold" in (workdir / "scripts" / "constraints.sgdc").read_text()
    assert "cold-start" in r.stdout


def test_readme_inference_wins_over_filelist(tmp_path):
    m, workdir, main = _make_tree(
        tmp_path, readme="**Top module**: inferred_top\n", filelist="other.v\n"
    )
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 0, r.stderr
    assert 'export TOP="${TOP:-inferred_top}"' in (workdir / "env.sh").read_text()


def test_infer_from_filelist_when_top_omitted(tmp_path):
    # No --top, no README: TOP inferred from filelist first entry ('dut').
    m, workdir, main = _make_tree(tmp_path)  # filelist -> rtl/dut.v
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 0, r.stderr
    assert 'export TOP="${TOP:-dut}"' in (workdir / "env.sh").read_text()


def test_filelist_synced_and_rebased(tmp_path):
    # rtl-design/filelist.txt -> scripts/filelist.txt with the +incdir + rebased paths.
    # Skip set is {#, blank} ONLY: a comment is dropped, real .v lines are rebased.
    m, workdir, main = _make_tree(
        tmp_path, filelist="# a comment\nrtl/dut.v\nrtl/sub/u.sv\n"
    )
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    gen = (workdir / "scripts" / "filelist.txt").read_text()
    assert "+incdir+../../../rtl-design" in gen
    assert "../../../rtl-design/rtl/dut.v" in gen
    assert "../../../rtl-design/rtl/sub/u.sv" in gen
    assert "a comment" not in gen  # comment skipped
    assert "bootstrap_lint_cdc" not in gen  # generated header names no retired .sh


def test_empty_filelist_fail_closed(tmp_path):
    # filelist with only comments/blanks -> 0 usable entries -> exit 1.
    m, workdir, main = _make_tree(tmp_path, filelist="# only a comment\n\n")
    # --top given so we pass inference and reach the filelist sync.
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 1
    assert "no usable RTL entries" in r.stderr


def test_no_rtl_filelist_keeps_template_filelist(tmp_path):
    # rtl-design/filelist.txt absent -> sync is a no-op; the MY_TOP-substituted
    # template filelist.txt stays (../../../rtl-design/MY_TOP.v -> .../dut.v).
    m, workdir, main = _make_tree(tmp_path, filelist=None)
    r = _run(
        m, workdir, main, extra=["--top", "dut"]
    )  # --top: no filelist to infer from
    assert r.returncode == 0, r.stderr
    gen = (workdir / "scripts" / "filelist.txt").read_text()
    assert "../../../rtl-design/dut.v" in gen and "MY_TOP" not in gen


def test_cant_infer_top_fail_closed(tmp_path):
    # No --top, no README, filelist has no usable RTL entry -> inference None -> exit 1.
    m, workdir, main = _make_tree(tmp_path, filelist="+incdir+x\n", readme=None)
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 1
    assert "cannot infer top" in r.stderr


def test_already_deployed_guard(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    assert _run(m, workdir, main, extra=["--top", "dut"]).returncode == 0
    r2 = _run(m, workdir, main, extra=["--top", "dut"])
    assert r2.returncode == 1
    assert "already deployed" in r2.stderr


def test_missing_template_dir_fail_closed(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    shutil.rmtree(tmp_path / "skills" / "lint-cdc" / "templates")
    r = _run(m, workdir, main, extra=["--top", "dut"])
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
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    assert "WARNING" in r.stderr and "periods disagree" in r.stderr


def test_relative_workdir_with_trailing_slash(tmp_path):
    # BP5: a relative --workdir resolves against the repo root (not cwd), and the
    # trailing slash is dropped before deploy. (The mirror's repo root is tmp_path.)
    m, workdir, main = _make_tree(tmp_path)
    proc = subprocess.run(
        [
            "python3",
            str(main),
            "bootstrap",
            "--module",
            m,
            "--workdir",
            "asic/M/Design/lint-cdc/runs/1/",  # relative + trailing slash
            "--top",
            "dut",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (workdir / "Makefile").is_file()  # resolved to the absolute location
    assert (workdir / "env.sh").is_file()
