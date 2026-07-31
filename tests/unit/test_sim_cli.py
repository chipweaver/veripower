# tests/unit/test_sim_cli.py
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"

_VERBS = (
    "bootstrap",
    "check-materialization",
    "finalize",
)


def _run(*argv):
    return subprocess.run(["python3", str(MAIN), *argv], capture_output=True, text=True)


def test_cli_help_lists_all_verbs():
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    for v in _VERBS:
        assert v in r.stdout, f"{v} missing from --help"


def test_cli_unknown_verb_exits_2():
    assert _run("bogus").returncode == 2


def test_cli_no_verb_exits_2():
    assert _run().returncode == 2


def test_classify_and_copy_baseline_verbs_removed(tmp_path):
    for verb in ("classify-delta", "copy-baseline"):
        r = subprocess.run(
            [sys.executable, str(MAIN), verb, "--workdir", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        # A true RED->GREEN discriminator: argparse's unknown-subcommand message
        # (not merely "missing a required argument", which a still-existing verb
        # could also produce), tolerant of the quoting style around the verb name.
        assert "invalid choice" in r.stderr
        assert verb in r.stderr


def test_validate_review_verb_removed(tmp_path):
    # The conformance review is prose the reviewer writes, and the one word a machine reads
    # off it is read by finalize, which is what makes the pass conditional on it. A verb that
    # told the main thread what it could see for itself enforced nothing.
    r = _run("validate-review", "--review", str(tmp_path / "conformance-review.md"))
    assert r.returncode != 0 and "invalid choice" in r.stderr
