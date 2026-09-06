"""The plan sidecars' own schemas, checked through the function that reads them.

power-scenarios.json had no lower bound, so `[]` validated. Downstream that is not "this
module has no power question": power-analysis iterates the table, measures nothing, and
returns a pass whose power_by_scenario is empty — a stage reporting success for work it
did not do. It only fails loudly when a requirements row bounds a dim the run never
measured, so a ledger with no power bound gets the vacuous pass.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/simulation-plan/scripts"))

from simplan._plan import PlanError, _read_validated  # noqa: E402

SCHEMA = "power-scenarios.schema.json"


def test_an_empty_power_scenario_table_is_refused(tmp_path):
    p = tmp_path / "power-scenarios.json"
    p.write_text("[]")
    with pytest.raises(PlanError, match="non-empty"):
        _read_validated(p, SCHEMA)


def test_one_row_is_enough(tmp_path):
    p = tmp_path / "power-scenarios.json"
    p.write_text('[{"id": "S1", "sequence_ref": "s1"}]')
    assert _read_validated(p, SCHEMA) == [{"id": "S1", "sequence_ref": "s1"}]
