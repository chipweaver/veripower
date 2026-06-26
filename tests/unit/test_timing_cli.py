# tests/unit/test_timing_cli.py
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/timing-analysis/scripts/timing/__main__.py"


def _run(*argv):
    return subprocess.run(["python3", str(MAIN), *argv], capture_output=True, text=True)


def test_cli_help_lists_both_verbs():
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    assert "bootstrap" in r.stdout and "finalize" in r.stdout


def test_cli_unknown_verb_exits_2():
    assert _run("bogus").returncode == 2


def test_cli_no_verb_exits_2():
    assert _run().returncode == 2
