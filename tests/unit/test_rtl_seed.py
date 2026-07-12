# tests/unit/test_rtl_seed.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"


def _run(canonical, workdir, check=True):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "seed",
            "--canonical",
            str(canonical),
            "--workdir",
            str(workdir),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def test_carries_unchanged_rtl_forward(tmp_path):
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "a.sv").write_text("module a; endmodule\n")
    (canon / ".child_reports.json").write_text('{"a": {}}')
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert (wd / "a.sv").read_text() == "module a; endmodule\n"
    assert (wd / ".child_reports.json").exists()


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


def test_does_not_copy_prior_run_workdirs(tmp_path):
    canon = tmp_path / "canon"
    (canon / "runs" / "1").mkdir(parents=True)
    (canon / "runs" / "1" / "junk.sv").write_text("x\n")
    (canon / "a.sv").write_text("a\n")
    wd = tmp_path / "runs" / "2"
    wd.mkdir(parents=True)
    _run(canon, wd)
    assert (wd / "a.sv").exists()
    assert not (wd / "runs").exists()  # prior run workdirs not carried in


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
