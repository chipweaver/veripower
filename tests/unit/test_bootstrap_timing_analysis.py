"""Tests for skills/timing-analysis/scripts/bootstrap_timing_analysis.sh.

The bootstrap derives REPO_ROOT from its own location ($SCRIPT_DIR/../../..), so
— like test_bootstrap_synthesis_incdir.py — we MIRROR skills/timing-analysis into
tmp_path and run the COPY, making REPO_ROOT resolve to tmp_path (not the real repo).
"""

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_tree(tmp_path, *, status="pass", top="sdc_controller", with_netlist=True):
    """Mirror skills/timing-analysis into tmp + build a synthesis prereq tree.

    Returns (module, workdir, bootstrap_path). The copied bootstrap's
    $SCRIPT_DIR/../../.. resolves REPO_ROOT to tmp_path.
    """
    shutil.copytree(
        REPO_ROOT / "skills" / "timing-analysis",
        tmp_path / "skills" / "timing-analysis",
    )
    m = top
    syn = tmp_path / "asic" / m / "Design" / "synthesis"
    (syn / "out").mkdir(parents=True)
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
        (syn / "out" / f"{top}_syn.sdc").write_text("# sdc\n")
    workdir = tmp_path / "asic" / m / "Design" / "timing-analysis" / "runs" / "1"
    bootstrap = (
        tmp_path
        / "skills"
        / "timing-analysis"
        / "scripts"
        / "bootstrap_timing_analysis.sh"
    )
    return m, workdir, bootstrap


def _run(module, workdir, bootstrap, extra=None):
    cmd = ["bash", str(bootstrap), "--module", module, "--workdir", str(workdir)]
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True)


def test_deploys_and_substitutes(tmp_path):
    m, workdir, bs = _make_tree(tmp_path)
    r = _run(m, workdir, bs)
    assert r.returncode == 0, r.stderr
    tcl = (workdir / "run_sta.tcl").read_text()
    assert "asic/sdc_controller" in tcl  # MY_MODULE substituted
    assert "MY_MODULE" not in tcl and "MY_WORKDIR" not in tcl
    cfg = (workdir / "config.tcl").read_text()
    assert "set TOP    sdc_controller" in cfg  # MY_TOP substituted
    assert "MY_TOP" not in cfg


def test_workdir_is_tree_root_relative(tmp_path):
    m, workdir, bs = _make_tree(tmp_path)
    assert _run(m, workdir, bs).returncode == 0
    tcl = (workdir / "run_sta.tcl").read_text()
    # WORKDIR must be tree-root-relative (pt_shell runs from the tree root).
    assert "set WORKDIR     asic/sdc_controller/Design/timing-analysis/runs/1" in tcl


def test_lib_db_captured_when_exported(tmp_path, monkeypatch):
    m, workdir, bs = _make_tree(tmp_path)
    monkeypatch.setenv("LIB_DB", "/home/eda/Foundry/TSMC.90/slow.db")
    assert _run(m, workdir, bs).returncode == 0
    cfg = (workdir / "config.tcl").read_text()
    assert "set LIB_DB /home/eda/Foundry/TSMC.90/slow.db" in cfg
    assert "FILL_IN_LIB_DB_PATH" not in cfg


def test_fail_closed_when_synthesis_not_pass(tmp_path):
    m, workdir, bs = _make_tree(tmp_path, status="fail")
    r = _run(m, workdir, bs)
    assert r.returncode != 0
    assert not (workdir / "run_sta.tcl").exists()


def test_fail_closed_when_netlist_missing(tmp_path):
    # Pass --top so we get past TOP-inference and hit the netlist-existence check.
    m, workdir, bs = _make_tree(tmp_path, with_netlist=False)
    r = _run(m, workdir, bs, extra=["--top", "sdc_controller"])
    assert r.returncode != 0
    assert not (workdir / "run_sta.tcl").exists()


def test_aborts_when_already_deployed(tmp_path):
    m, workdir, bs = _make_tree(tmp_path)
    assert _run(m, workdir, bs).returncode == 0
    r2 = _run(m, workdir, bs)
    assert r2.returncode != 0
    assert "already deployed" in (r2.stderr + r2.stdout)
