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


def test_requirements_helper_keeps_only_the_rows_this_stage_judges(tmp_path):
    import json
    import sys

    import pytest

    sys.path.insert(0, str(ROOT / "skills" / "synthesis" / "scripts"))
    from synthesis import requirements as rq

    rows = [
        {
            "id": "R-1",
            "verbatim": "area",
            "judge": "synthesis",
            "target": {"dim": "area_um2", "op": "<=", "value": 450000},
        },
        {
            "id": "R-2",
            "verbatim": "power",
            "judge": "power-analysis",
            "target": {"dim": "power_mw", "op": "<=", "value": 5},
        },
        {"id": "R-3", "verbatim": "synthesizable", "judge": "synthesis"},
    ]
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "requirements.json").write_text(json.dumps(rows))
    (tmp_path / "dispatch.json").write_text(
        json.dumps({"inputs": {"requirements": str(spec)}})
    )
    mine = rq.mine(rq.load(tmp_path))
    assert [r["id"] for r in mine] == ["R-1", "R-3"]
    assert rq.met(400000, rows[0]["target"]) and not rq.met(450001, rows[0]["target"])
    # merge: one entry per row, in ledger order; a missing or foreign verdict is refused
    computed = [{"id": "R-1", "met": True, "actual": 400000}]
    declared = rq.parse_declared(
        '[{"id": "R-3", "met": true, "actual": "elaborates clean"}]'
    )
    assert [e["id"] for e in rq.merge(mine, computed, declared)] == ["R-1", "R-3"]
    with pytest.raises(ValueError, match="R-3"):
        rq.merge(mine, computed, [])
    with pytest.raises(ValueError, match="R-2"):
        rq.merge(mine, computed, declared + [{"id": "R-2", "met": True}])
    with pytest.raises(ValueError):
        rq.parse_declared('[{"id": "R-3", "met": "yes"}]')
    assert rq.parse_declared(None) == []
