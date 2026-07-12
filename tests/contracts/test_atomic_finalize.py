from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FINALIZERS = [
    "specification/scripts/spec/result.py",
    "simulation-plan/scripts/simplan/result.py",
    "rtl-design/scripts/rtl/result.py",
    "lint-cdc/scripts/lintcdc/result.py",
    "simulation/scripts/sim/result.py",
    "synthesis/scripts/synthesis/result.py",
    "timing-analysis/scripts/timing/result.py",
    "power-analysis/scripts/power/result.py",
    "frontend-signoff/scripts/signoff/result.py",
    "simulation-triage/scripts/simtriage/result.py",  # triage also writes result.json
]


@pytest.mark.parametrize("rel", FINALIZERS)
def test_result_json_written_atomically(rel):
    src = (ROOT / "skills" / rel).read_text()
    assert "result.json.tmp" in src, f"{rel}: no temp file"
    assert ".replace(" in src, f"{rel}: no atomic rename"
    # the non-atomic direct write must be gone
    assert '"result.json").write_text(json.dumps' not in src, (
        f"{rel}: still direct-writes"
    )
