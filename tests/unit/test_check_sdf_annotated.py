import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO
    / "skills"
    / "power-analysis"
    / "templates"
    / "scripts"
    / "check_sdf_annotated.sh"
)


def _run(tmp_path, log_text):
    log = tmp_path / "gls-compile-log.txt"
    log.write_text(log_text)
    return subprocess.run(["bash", str(SCRIPT), str(log)], capture_output=True)


def test_zero_annotated_fails(tmp_path):
    r = _run(tmp_path, "Back-annotation\nNumber of cells annotated = 0\n")
    assert r.returncode == 1
    assert (
        b"phase=compile category=sdf" in r.stderr
    )  # A: producer self-reports phase too


def test_nonzero_annotated_passes(tmp_path):
    r = _run(tmp_path, "Number of cells annotated = 12345\n")
    assert r.returncode == 0


def test_no_summary_line_fails_loud(tmp_path):
    r = _run(tmp_path, "nothing about back annotation here\n")
    assert r.returncode == 1
    assert (
        b"phase=compile category=sdf" in r.stderr
    )  # A: producer self-reports phase too
    assert b"no SDF annotation summary" in r.stderr  # distinct from a real 0 (P3)
