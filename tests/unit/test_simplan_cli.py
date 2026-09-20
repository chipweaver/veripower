# tests/unit/test_simplan_cli.py
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-plan/scripts/simplan/__main__.py"

VERBS = (
    "check-scaffold",
    "finalize",
)


def run(*argv):
    return subprocess.run(["python3", str(MAIN), *argv], capture_output=True, text=True)


def test_cli_help_lists_every_verb():
    r = run("--help")
    assert r.returncode == 0, r.stderr
    for v in VERBS:
        assert v in r.stdout, f"{v} missing from --help"


def test_cli_unknown_verb_exits_2():
    assert run("bogus").returncode == 2


def test_cli_no_verb_exits_2():
    assert run().returncode == 2


def test_seed_verb_removed(tmp_path):
    r = run("seed", "--workdir", str(tmp_path))
    assert r.returncode != 0  # argparse rejects an unknown subcommand


def test_validate_review_verb_removed(tmp_path):
    # The plan-adequacy review is prose the reviewer writes; nothing reduces it to a verdict.
    r = run("validate-review", "--review", str(tmp_path / "plan-review.json"))
    assert r.returncode != 0
