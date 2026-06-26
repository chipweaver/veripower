# tests/unit/test_timing_bootstrap.py
"""timing bootstrap — Python port of the retired bootstrap_timing_analysis.sh.

Two layers: in-process unit tests of infer_top (BP1), and subprocess "mirror"
tests of full deploy behavior (BP2-BP10). The mirror copies skills/timing-analysis
into a tmp tree so the package's _REPO_ROOT (= _HERE.parents[4]) resolves to
tmp_path, not the real repo — same trick the old shell test used.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "timing-analysis" / "scripts"))
from timing import bootstrap  # noqa: E402


# ── BP1: infer_top (in-process, precise) ──────────────────────────────────────
def test_infer_top_single_match(tmp_path):
    out = tmp_path / "Design" / "synthesis" / "out"
    out.mkdir(parents=True)
    (out / "sdc_controller_syn.v").write_text("// netlist\n")
    assert bootstrap.infer_top(tmp_path / "Design" / "synthesis") == "sdc_controller"


def test_infer_top_none_when_absent(tmp_path):
    (tmp_path / "Design" / "synthesis" / "out").mkdir(parents=True)
    assert bootstrap.infer_top(tmp_path / "Design" / "synthesis") is None


def test_infer_top_none_when_multiple(tmp_path):
    out = tmp_path / "Design" / "synthesis" / "out"
    out.mkdir(parents=True)
    (out / "a_syn.v").write_text("x")
    (out / "b_syn.v").write_text("x")
    assert bootstrap.infer_top(tmp_path / "Design" / "synthesis") is None


# ── BP2-BP10: full deploy (subprocess mirror) ─────────────────────────────────
def _make_tree(
    tmp_path,
    *,
    status="pass",
    top="sdc_controller",
    with_netlist=True,
    with_sdc=True,
    with_result=True,
):
    """Mirror skills/timing-analysis into tmp + build a synthesis prereq tree.

    Returns (module, workdir, main). The copied package's _HERE.parents[4]
    resolves _REPO_ROOT to tmp_path.
    """
    shutil.copytree(
        REPO_ROOT / "skills" / "timing-analysis",
        tmp_path / "skills" / "timing-analysis",
    )
    m = top
    syn = tmp_path / "asic" / m / "Design" / "synthesis"
    (syn / "out").mkdir(parents=True)
    if with_result:
        (syn / "result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "synthesis",
                    "module": m,
                    "produced_at": "2026-06-08T00:00:00Z",
                    "status": status,
                    "artifacts": [],
                    "stage_specific": {"ppa_actual": []},
                }
            )
        )
    if with_netlist:
        (syn / "out" / f"{top}_syn.v").write_text("// netlist\n")
    if with_sdc:
        (syn / "out" / f"{top}_syn.sdc").write_text("# sdc\n")
    workdir = tmp_path / "asic" / m / "Design" / "timing-analysis" / "runs" / "1"
    main = (
        tmp_path / "skills" / "timing-analysis" / "scripts" / "timing" / "__main__.py"
    )
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


def test_deploys_and_substitutes(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    r = _run(m, workdir, main)
    assert r.returncode == 0, r.stderr
    tcl = (workdir / "run_sta.tcl").read_text()
    assert (
        "asic/sdc_controller" in tcl
    )  # MODULE_ROOT substituted (abs, contains asic/<m>)
    assert "MY_MODULE" not in tcl and "MY_WORKDIR" not in tcl
    cfg = (workdir / "config.tcl").read_text()
    assert "set TOP    sdc_controller" in cfg  # MY_TOP substituted
    assert "MY_TOP" not in cfg


def test_workdir_and_module_root_are_absolute(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    assert _run(m, workdir, main).returncode == 0
    tcl = (workdir / "run_sta.tcl").read_text()
    # pt_shell runs from the workdir; MODULE_ROOT/WORKDIR are absolute so reads resolve
    # from any CWD and PT's auto-logs land inside the gitignored workdir.
    assert f"set WORKDIR     {workdir}" in tcl
    assert str(tmp_path / "asic" / m) in tcl  # MODULE_ROOT is absolute
    assert "set WORKDIR     asic/" not in tcl  # the old tree-root-relative form is gone


def test_lib_db_captured_when_exported(tmp_path, monkeypatch):
    m, workdir, main = _make_tree(tmp_path)
    monkeypatch.setenv("LIB_DB", "/home/eda/Foundry/TSMC.90/slow.db")
    assert _run(m, workdir, main).returncode == 0
    cfg = (workdir / "config.tcl").read_text()
    assert "set LIB_DB /home/eda/Foundry/TSMC.90/slow.db" in cfg
    assert "FILL_IN_LIB_DB_PATH" not in cfg


def test_lib_db_empty_env_falls_back(tmp_path, monkeypatch):
    # BP8: shell `${LIB_DB:-FILL_IN_LIB_DB_PATH}` falls back on unset OR empty. An
    # exported-but-empty LIB_DB must keep the placeholder, else config.tcl gets
    # `set LIB_DB ` (empty value) which result.read_lib_db's `\S+` regex won't match.
    m, workdir, main = _make_tree(tmp_path)
    monkeypatch.setenv("LIB_DB", "")
    assert _run(m, workdir, main).returncode == 0
    cfg = (workdir / "config.tcl").read_text()
    assert "set LIB_DB FILL_IN_LIB_DB_PATH" in cfg  # fallback, not an empty value


def test_fail_closed_when_synthesis_not_pass(tmp_path):
    m, workdir, main = _make_tree(tmp_path, status="fail")
    r = _run(m, workdir, main)
    assert r.returncode == 1
    assert not (workdir / "run_sta.tcl").exists()


def test_fail_closed_when_synthesis_result_missing(tmp_path):
    # The .sh guards a missing result.json (line 75) but had NO test — §5.3 mandate.
    m, workdir, main = _make_tree(tmp_path, with_result=False)
    r = _run(m, workdir, main)
    assert r.returncode == 1
    assert "missing" in r.stderr
    assert not (workdir / "run_sta.tcl").exists()


def test_fail_closed_when_netlist_missing(tmp_path):
    # Pass --top so we get past TOP-inference and hit the netlist-existence check.
    m, workdir, main = _make_tree(tmp_path, with_netlist=False)
    r = _run(m, workdir, main, extra=["--top", "sdc_controller"])
    assert r.returncode == 1
    assert "external reference" in r.stderr
    assert not (workdir / "run_sta.tcl").exists()


def test_fail_closed_when_sdc_missing(tmp_path):
    # BP3 is two-sided: the netlist alone is not enough; PT also reads the SDC.
    m, workdir, main = _make_tree(tmp_path, with_sdc=False)
    r = _run(m, workdir, main, extra=["--top", "sdc_controller"])
    assert r.returncode == 1
    assert "external reference" in r.stderr
    assert not (workdir / "run_sta.tcl").exists()


def test_cant_infer_top_no_netlist(tmp_path):
    # No --top and no out/*_syn.v -> inference returns None -> fail-closed exit 1.
    m, workdir, main = _make_tree(tmp_path, with_netlist=False)
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 1
    assert "cannot infer top" in r.stderr


def test_cant_infer_top_multiple(tmp_path):
    # Two out/*_syn.v -> inference is ambiguous -> fail-closed exit 1.
    m, workdir, main = _make_tree(tmp_path)
    syn_out = tmp_path / "asic" / m / "Design" / "synthesis" / "out"
    (syn_out / "other_syn.v").write_text("// second netlist\n")
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 1
    assert "cannot infer top" in r.stderr


def test_aborts_when_already_deployed(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    assert _run(m, workdir, main).returncode == 0
    r2 = _run(m, workdir, main)
    assert r2.returncode == 1
    assert "already deployed" in (r2.stderr + r2.stdout)


def test_missing_template_dir_fail_closed(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    shutil.rmtree(tmp_path / "skills" / "timing-analysis" / "templates")
    r = _run(m, workdir, main, extra=["--top", "sdc_controller"])
    assert r.returncode == 1
    assert "missing" in r.stderr
    assert not (workdir / "run_sta.tcl").exists()


def test_relative_workdir_with_trailing_slash(tmp_path):
    # BP5: a relative --workdir resolves against the repo root (not cwd), and the
    # trailing slash is dropped (type=Path) before deploy. (The mirror's repo root is
    # tmp_path, so the relative path lands at the same absolute workdir.)
    m, workdir, main = _make_tree(tmp_path)
    proc = subprocess.run(
        [
            "python3",
            str(main),
            "bootstrap",
            "--module",
            m,
            "--workdir",
            "asic/sdc_controller/Design/timing-analysis/runs/1/",  # relative + trailing slash
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (workdir / "run_sta.tcl").is_file()  # resolved to the absolute location
    assert (workdir / "config.tcl").is_file()
