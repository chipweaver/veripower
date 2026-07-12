# tests/unit/test_sim_freeze.py
"""sim freeze verb — deterministic copy of the prior canonical TB + rtl_filelist regen.

Subprocess mirror tests: run the real shipped verb with cwd set to a tmp design-tree root
(the freeze verb anchors the design tree on the CWD, matching bootstrap/kernel.py).
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "skills" / "simulation" / "scripts" / "sim" / "__main__.py"


def _tree(tmp_path):
    module = "alu"
    rtl = tmp_path / "asic" / module / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    (rtl / "filelist.txt").write_text("rtl/alu.v\n+incdir+inc\n")
    canon = tmp_path / "asic" / module / "Verification" / "simulation"
    (canon / "tb" / "uvm" / "agent").mkdir(parents=True)
    (canon / "scripts").mkdir(parents=True)
    (canon / "tests").mkdir(parents=True)
    (canon / "Makefile").write_text("simv:\n\techo build\n")
    (canon / "env.sh").write_text("export TOP=alu\n")
    (canon / "filelist.f").write_text("tb/uvm/agent/x.sv\n")
    (canon / "rtl_filelist.f").write_text("STALE\n")
    (canon / "tb" / "uvm" / "agent" / "x.sv").write_text("class x; endclass\n")
    (canon / "scripts" / "run.sh").write_text("echo run\n")
    (canon / "tests" / "testlist.json").write_text("[]\n")
    (canon / "conformance-review.json").write_text('{"verdict":"ok","findings":[]}\n')
    (canon / "verify-handoff.json").write_text(
        '{"module":"alu","testpoints":[]}\n'
    )  # promoted
    # per-run outputs that MUST NOT be copied
    (canon / "regression-log.txt").write_text("RESULT t PASS\n")
    (canon / "structural-coverage.json").write_text("{}\n")
    (canon / "result.json").write_text("{}\n")
    wd = tmp_path / "asic" / module / "Verification" / "simulation" / "runs" / "2"
    return module, canon, wd


def _run(module, canon, wd, tree_root, mode="freeze"):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "copy-baseline",
            "--module",
            module,
            "--workdir",
            str(wd),
            "--canonical",
            str(canon),
            "--mode",
            mode,
        ],
        cwd=str(tree_root),
        capture_output=True,
        text=True,
    )


def test_copies_whitelist_and_regenerates_rtl_filelist(tmp_path):
    module, canon, wd = _tree(tmp_path)
    r = _run(module, canon, wd, tmp_path)
    assert r.returncode == 0, r.stderr
    for f in ("Makefile", "env.sh", "filelist.f", "conformance-review.json"):
        assert (wd / f).is_file(), f
    assert (wd / "tb/uvm/agent/x.sv").is_file()
    assert (wd / "tests/testlist.json").is_file()
    rtlf = (wd / "rtl_filelist.f").read_text()
    assert (
        "STALE" not in rtlf and "Design/rtl-design/rtl/alu.v" in rtlf
    )  # regenerated, rebased


def test_copies_promoted_handoff_excludes_per_run_outputs(tmp_path):
    module, canon, wd = _tree(tmp_path)
    assert _run(module, canon, wd, tmp_path).returncode == 0
    assert (
        wd / "verify-handoff.json"
    ).is_file()  # promoted -> copied (deterministic reuse)
    assert (wd / "conformance-review.json").is_file()
    for f in ("regression-log.txt", "structural-coverage.json", "result.json"):
        assert not (wd / f).exists(), f


def test_aborts_when_workdir_already_populated(tmp_path):
    module, canon, wd = _tree(tmp_path)
    assert _run(module, canon, wd, tmp_path).returncode == 0
    r2 = _run(module, canon, wd, tmp_path)
    assert r2.returncode == 1 and "already" in (r2.stderr + r2.stdout)


def test_fails_when_canonical_tb_missing(tmp_path):
    import shutil

    module, canon, wd = _tree(tmp_path)
    shutil.rmtree(Path(canon) / "tb")
    r = _run(module, canon, wd, tmp_path)
    assert r.returncode == 1 and "canonical TB" in r.stderr


def test_fails_when_conformance_review_missing(tmp_path):
    # P1-A carry-forward is asserted, not silently skipped.
    module, canon, wd = _tree(tmp_path)
    (Path(canon) / "conformance-review.json").unlink()
    r = _run(module, canon, wd, tmp_path)
    assert r.returncode == 1 and "conformance-review.json" in r.stderr


def test_fails_when_verify_handoff_missing(tmp_path):
    # verify-handoff.json is a promoted carry-forward (asserted, not silently skipped).
    module, canon, wd = _tree(tmp_path)
    (Path(canon) / "verify-handoff.json").unlink()
    r = _run(module, canon, wd, tmp_path)
    assert r.returncode == 1 and "verify-handoff.json" in r.stderr


def test_patch_mode_copies_tb_code_only(tmp_path):
    module, canon, wd = _tree(tmp_path)
    r = _run(module, canon, wd, tmp_path, mode="patch")
    assert r.returncode == 0, r.stderr
    for f in ("Makefile", "env.sh", "filelist.f"):
        assert (wd / f).is_file(), f
    assert (wd / "tb/uvm/agent/x.sv").is_file()
    # 判决产物 NOT carried in patch mode (child re-authors / full conformance re-runs)
    assert not (wd / "conformance-review.json").exists()
    assert not (wd / "verify-handoff.json").exists()
    rtlf = (wd / "rtl_filelist.f").read_text()
    assert "STALE" not in rtlf and "Design/rtl-design/rtl/alu.v" in rtlf


def test_patch_mode_succeeds_without_judged_artifacts(tmp_path):
    # smoke-fail 基线：conformance-review.json / verify-handoff.json 都没产出 -> patch 仍成功
    module, canon, wd = _tree(tmp_path)
    (canon / "conformance-review.json").unlink()
    (canon / "verify-handoff.json").unlink()
    assert _run(module, canon, wd, tmp_path, mode="patch").returncode == 0
