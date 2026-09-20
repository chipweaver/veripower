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


def load_requirements_module(stage: str, pkg: str):
    sys.path.insert(0, str(ROOT / "skills" / stage / "scripts"))
    return __import__(f"{pkg}.requirements", fromlist=["requirements"])


@pytest.mark.parametrize(
    "stage,pkg", [("timing-analysis", "timing"), ("lint-cdc", "lintcdc")]
)
def test_stages_refuse_an_unsupported_bounded_dimension(tmp_path, stage, pkg):
    rq = load_requirements_module(stage, pkg)
    row = {
        "id": "R-X",
        "judge": stage,
        "target": {"dim": "power_mw", "op": "<=", "value": 5},
    }
    (tmp_path / "requirements.json").write_text(json.dumps([row]))
    (tmp_path / "dispatch.json").write_text(
        json.dumps({"inputs": {"requirements": str(tmp_path)}})
    )
    with pytest.raises(ValueError) as exc:
        rq.load_requirements(tmp_path)
    assert "R-X" in str(exc.value)


def test_synthesis_refuses_a_dim_it_does_not_measure():
    sys.path.insert(0, str(ROOT / "skills" / "synthesis" / "scripts"))
    from synthesis import result

    reports = ROOT / "tests/unit/fixtures/synthesis-reports/reports"
    row = {"id": "R-X", "target": {"dim": "power_mw", "op": "<=", "value": 5}}
    with pytest.raises(ValueError) as exc:
        result.run(reports, [row])
    assert "power_mw" in str(exc.value) and "does not measure" in str(exc.value)


def test_power_refuses_a_dim_it_does_not_measure(tmp_path):
    sys.path.insert(0, str(ROOT / "skills" / "power-analysis" / "scripts"))
    from power import result

    reports = ROOT / "tests/unit/fixtures/power-reports"
    wd = tmp_path / "measurement"
    (wd / "saif").mkdir(parents=True)
    shutil.copy2(reports / "active.saif", wd / "saif/workload.saif")
    (wd / "saif/workload.status").write_text("PASS\n")
    destination = wd / "reports_ptpx/workload"
    destination.mkdir(parents=True)
    shutil.copy2(reports / "rounded-power.rpt", destination / "power_flat.rpt")
    (destination / "switching_activity.rpt").write_text(" Nets 4(100.00%) 0(0.00%) 4\n")
    (tmp_path / "power-scenarios.json").write_text('[{"id":"workload"}]')
    row = {"id": "R-X", "target": {"dim": "area_um2", "op": "<=", "value": 5}}
    with pytest.raises(ValueError) as exc:
        result.run(tmp_path, wd, [row])
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
