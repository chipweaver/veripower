# tests/unit/test_rtl_cli.py
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"

_VERBS = ("finalize",)

# The stage authors its own sidecars and acts on its own reviews; finalize is the only step
# whose output another component consumes, so it is the only step that needs a script.
_REMOVED_VERBS = (
    "check-partition",
    "assemble",
    "validate-review",
    "check-conformance",
    "seed",
)


def _run(*argv):
    return subprocess.run(["python3", str(MAIN), *argv], capture_output=True, text=True)


def test_cli_help_lists_every_verb():
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    for v in _VERBS:
        assert v in r.stdout, f"{v} missing from --help"


def test_removed_verbs_stay_removed(tmp_path):
    for v in _REMOVED_VERBS:
        assert _run(v, "--workdir", str(tmp_path)).returncode != 0, (
            f"{v} still dispatches"
        )
        assert v not in _run("--help").stdout, f"{v} still advertised in --help"


def test_cli_unknown_verb_exits_2():
    assert _run("bogus").returncode == 2


def test_cli_no_verb_exits_2():
    assert _run().returncode == 2
