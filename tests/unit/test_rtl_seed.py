# tests/unit/test_rtl_seed.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"
sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))


def _run(canonical, workdir, *extra, check=True):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "seed",
            "--canonical",
            str(canonical),
            "--workdir",
            str(workdir),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def test_carries_unchanged_rtl_forward(tmp_path):
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "a.sv").write_text("module a; endmodule\n")
    (canon / "filelist.txt").write_text("a.sv\n")
    (canon / "README.md").write_text("**Top module**: a\n")
    (canon / ".child_reports.json").write_text('{"a": {}}')
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert (wd / "a.sv").read_text() == "module a; endmodule\n"
    assert (wd / "filelist.txt").exists()
    assert (wd / "README.md").exists()
    assert (wd / ".child_reports.json").exists()


def test_carries_nested_rtl_and_headers(tmp_path):
    # Children author their own file/include layout (child-task-contract.md): nested
    # rel-paths and .vh/.svh headers must survive the carry, or promote's GC loses them.
    canon = tmp_path / "canon"
    (canon / "core" / "include").mkdir(parents=True)
    (canon / "core" / "alu.v").write_text("module alu; endmodule\n")
    (canon / "core" / "include" / "defs.svh").write_text("`define W 8\n")
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert (wd / "core" / "alu.v").exists()
    assert (wd / "core" / "include" / "defs.svh").exists()


def test_never_carries_adjudication_artifacts(tmp_path):
    # Room-birth hygiene (§7.2): result.json is never seeded (a carried-in stale envelope
    # would be reaped blocked/stale_result); semantic-review.json is never seeded either.
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "a.v").write_text("module a; endmodule\n")
    (canon / "result.json").write_text('{"status":"pass"}')
    (canon / "semantic-review.json").write_text('{"pin":1}')
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert (wd / "a.v").exists()
    assert not (wd / "result.json").exists()
    assert not (wd / "semantic-review.json").exists()


def test_seed_does_not_materialize_fresh_reports(tmp_path):
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "a.v").write_text("module a; endmodule\n")
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert not (wd / "fresh_reports.json").exists()  # rework rounds author their own


def test_ledger_listed_non_hdl_files_carried(tmp_path):
    # Children author their own layout and may list non-HDL support files (e.g. a
    # $readmemh .mem image) in their report `files`; those are promoted products the
    # ledger still names, so dropping them would make the next finalize's artifacts[]
    # point at a missing path and crash promote.
    canon = tmp_path / "canon"
    (canon / "core").mkdir(parents=True)
    (canon / "core" / "alu.v").write_text("module alu; endmodule\n")
    (canon / "core" / "rom_init.mem").write_text("00ff\n")
    (canon / ".child_reports.json").write_text(
        json.dumps({"core": {"files": ["core/alu.v", "core/rom_init.mem"]}})
    )
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert (wd / "core" / "rom_init.mem").read_text() == "00ff\n"
    assert (wd / "core" / "alu.v").exists()


def test_ledger_escape_paths_ignored(tmp_path):
    # A corrupt/hostile ledger entry must never let seed copy from outside canonical.
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "a.v").write_text("module a; endmodule\n")
    (tmp_path / "outside.mem").write_text("evil\n")
    (canon / ".child_reports.json").write_text(
        json.dumps({"x": {"files": ["../outside.mem", "/etc/passwd"]}})
    )
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert not (wd / "outside.mem").exists()
    assert (wd / "a.v").exists()


def test_no_clobber_preserves_fresh_subset_F3(tmp_path):
    # Resume: child B already authored new RTL into the workdir before re-seed.
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "b.sv").write_text("STALE\n")
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    (wd / "b.sv").write_text("FRESH\n")  # freshly-authored subset work
    _run(canon, wd)
    assert (wd / "b.sv").read_text() == "FRESH\n"  # never clobbered


def test_first_run_no_canonical_is_noop(tmp_path):
    wd = tmp_path / "runs" / "1"
    wd.mkdir(parents=True)
    r = _run(tmp_path / "does_not_exist", wd)
    assert json.loads(r.stdout)["count"] == 0


def test_does_not_copy_prior_run_workdirs_or_promote_tmp(tmp_path):
    canon = tmp_path / "canon"
    (canon / "runs" / "1").mkdir(parents=True)
    (canon / "runs" / "1" / "junk.sv").write_text("x\n")
    (canon / ".promote-tmp").mkdir()
    (canon / ".promote-tmp" / "leftover.v").write_text("x\n")
    (canon / "a.sv").write_text("a\n")
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert (wd / "a.sv").exists()
    assert not (wd / "runs").exists()  # prior run workdirs not carried in
    assert not (wd / ".promote-tmp").exists()  # promote internals not carried in


def test_canonical_defaults_to_workdir_grandparent_S3(tmp_path):
    # Mirrors kernel.py's layout: workdir = <canonical>/runs/<N>; omit --canonical.
    canonical = tmp_path / "rtl-design"
    wd = canonical / "runs" / "2"
    wd.mkdir(parents=True)
    (canonical / "a.sv").write_text("module a; endmodule\n")
    subprocess.run(
        ["python3", str(MAIN), "seed", "--workdir", str(wd)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert (wd / "a.sv").read_text() == "module a; endmodule\n"
