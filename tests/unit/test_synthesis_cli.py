# tests/unit/test_synthesis_cli.py
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/synthesis/scripts/synthesis/__main__.py"


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


def test_read_ppa_targets_keeps_only_the_dims_this_stage_gates(tmp_path):
    import json
    import sys

    sys.path.insert(0, str(ROOT / "skills" / "synthesis" / "scripts"))
    from synthesis.__main__ import read_ppa_targets

    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "ppa.json").write_text(
        json.dumps(
            [
                {"dim": "area_um2", "target": 450000},
                {"dim": "timing_slack_ns", "target": 0.0},
                {"dim": "power_mw", "target": 5.0},  # power-analysis judges this one
            ]
        )
    )
    (tmp_path / "dispatch.json").write_text(json.dumps({"inputs": {"ppa": str(spec)}}))
    assert read_ppa_targets(tmp_path) == {"area_um2": 450000, "timing_slack_ns": 0.0}

    (spec / "ppa.json").unlink()  # specification declared none -> nothing gated
    assert read_ppa_targets(tmp_path) == {}
