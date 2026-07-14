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


def test_completion_marker_without_count_passes(tmp_path):
    # Real VCS (e.g. L-2016.06) prints begin/completed markers + a Total errors/warnings
    # block but NO "Number of ... annotated" count line; the completed marker is the
    # success signature.
    r = _run(
        tmp_path,
        "   ***    SDF annotation begin: Tue Jul 14 02:06:43 2026\n"
        "Total errors: 8153\nTotal warnings: 173577\n"
        "   ***    SDF annotation completed: Tue Jul 14 02:06:46 2026\n",
    )
    assert r.returncode == 0


def test_begin_without_completed_fails_loud(tmp_path):
    # Annotation started but never completed (crashed mid-pass) → fail loud, not a pass.
    r = _run(tmp_path, "   ***    SDF annotation begin: Tue Jul 14 02:06:43 2026\n")
    assert r.returncode == 1
    assert b"no SDF annotation summary" in r.stderr


def test_real_vcs_fixture_passes():
    # Regression: the plugin's own captured real VCS log (begin/completed markers, no
    # count line) must pass this gate rather than false-fail on format.
    fixture = (
        REPO
        / "tests"
        / "unit"
        / "fixtures"
        / "power-tpu_top"
        / "real"
        / "gls-compile-log.txt"
    )
    r = subprocess.run(["bash", str(SCRIPT), str(fixture)], capture_output=True)
    assert r.returncode == 0, r.stderr
