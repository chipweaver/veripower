"""A stage refuses a bound it cannot measure, and says which.

A ledger row names a dimension; the stage that judges it names the number it reads. Nothing
guaranteed the two were the same quantity, and the stages disagreed about what to do when
handed a dim they do not measure: simulation refused, synthesis raised a KeyError, and
power-analysis never looked at the dim at all — a row asking for an area bound was judged
`met: true, actual: 1.759` against a reading in milliwatts, at exit 0.

The one thing keeping the other three correct was a table in a fourth skill
(`spec/sidecar.py:TARGET_DIMS`), which had already drifted: it listed no dimension for
timing-analysis, though PrimeTime reports slack natively. Each stage now owns the fact,
because each stage is the only party that both declares and implements its own measurement.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _rq(stage: str, pkg: str):
    sys.path.insert(0, str(ROOT / "skills" / stage / "scripts"))
    return __import__(f"{pkg}.requirements", fromlist=["requirements"])


@pytest.mark.parametrize(
    "stage,pkg", [("timing-analysis", "timing"), ("lint-cdc", "lintcdc")]
)
def test_a_stage_that_measures_nothing_refuses_a_bounded_row(stage, pkg):
    rq = _rq(stage, pkg)
    row = {
        "id": "R-X",
        "judge": stage,
        "target": {"dim": "power_mw", "op": "<=", "value": 5},
    }
    with pytest.raises(ValueError) as exc:
        rq.mine([row])
    assert "R-X" in str(exc.value) and "measures no dimension" in str(exc.value)


def test_synthesis_refuses_a_dim_it_does_not_measure():
    sys.path.insert(0, str(ROOT / "skills" / "synthesis" / "scripts"))
    from synthesis import result

    reports = ROOT / "tests/unit/fixtures/synthesis-golden/reports"
    row = {"id": "R-X", "target": {"dim": "power_mw", "op": "<=", "value": 5}}
    with pytest.raises(ValueError) as exc:
        result.run(reports, [row])
    assert "power_mw" in str(exc.value) and "does not measure" in str(exc.value)


def test_power_refuses_a_dim_it_does_not_measure(tmp_path):
    sys.path.insert(0, str(ROOT / "skills" / "power-analysis" / "scripts"))
    from power import result

    golden = ROOT / "tests/unit/fixtures/power-golden"
    wd = tmp_path / "wd"
    shutil.copytree(golden / "real", wd)
    # One PASS token per scenario: the gate-level verdict base_test writes, absent from the
    # fixture. Without it the run fails before it ever reaches a verdict.
    for saif in (wd / "saif").glob("*.saif"):
        saif.with_suffix(".status").write_text("PASS\n")
    row = {"id": "R-X", "target": {"dim": "area_um2", "op": "<=", "value": 5}}
    with pytest.raises(ValueError) as exc:
        result.run(golden / "plan", wd, [row])
    assert "area_um2" in str(exc.value) and "does not measure" in str(exc.value)


def test_every_verdict_names_its_measurement():
    # The envelope requires it, so a stage that forgets costs the round a blocked outcome
    # rather than a routable one.
    env = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    assert "measured" in env["$defs"]["requirement_verdict"]["required"]


def test_the_ledger_does_not_enumerate_the_dims_again():
    # The table this replaced was one of three copies; the ledger schema held another, as an
    # enum plus a per-stage sentence in its description. A dim list here is a home that cannot
    # be kept true, because the stage is the only party that knows what it reads.
    schema = json.loads(
        (ROOT / "skills/specification/references/requirements.schema.json").read_text()
    )
    dim = schema["items"]["properties"]["target"]["properties"]["dim"]
    assert "enum" not in dim, "requirements.schema.json enumerates target dims again"
