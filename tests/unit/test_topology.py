import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "framework" / "scripts"))

import state
import topology


def test_constant_integrity():
    for s in topology.FORWARD_PRIORITY:
        assert s in topology.PREREQ_OF
        assert s in topology.SKILL_OF
        assert s in topology._RESULT_DIR


def test_is_dag_ancestor():
    assert topology.is_dag_ancestor("rtl-design", "lint-cdc")
    assert topology.is_dag_ancestor("specification", "frontend-signoff")
    assert not topology.is_dag_ancestor("lint-cdc", "rtl-design")


def test_descendants_bfs_order():
    # specification is the root; every other stage is downstream.
    d = topology.descendants("specification")
    assert d[0] == "simulation-plan"  # nearest child first (BFS)
    assert set(d) == set(topology.FORWARD_PRIORITY) - {"specification"}


def test_eligible_forward_first_run():
    task = {
        "stages": {
            s: {
                "status": "not_started",
                "freshness": "clean",
                "current_run": None,
                "in_flight": [],
            }
            for s in topology.FORWARD_PRIORITY
        }
    }
    assert topology.eligible("specification", task)  # no prereqs
    assert not topology.eligible("simulation-plan", task)  # prereq not pass


def test_eligible_stale_is_eligible_inprogress_clean_is_not():
    task = {
        "stages": {
            s: {
                "status": "pass",
                "freshness": "clean",
                "current_run": 1,
                "in_flight": [],
            }
            for s in topology.FORWARD_PRIORITY
        }
    }
    # rtl-design stale (cascade) with sim-plan pass/clean → eligible (rework)
    task["stages"]["rtl-design"] = {
        "status": "pass",
        "freshness": "stale",
        "current_run": 1,
        "in_flight": [],
    }
    assert topology.eligible("rtl-design", task)
    # in_progress/clean → never eligible (already running)
    task["stages"]["lint-cdc"] = {
        "status": "in_progress",
        "freshness": "clean",
        "current_run": 1,
        "in_flight": [{"run": 1}],
    }
    assert not topology.eligible("lint-cdc", task)


def test_state_reexports_are_identical_objects():
    # M2: 118 test refs + verify.py:23 read state.<symbol>; must stay valid.
    assert state.FORWARD_PRIORITY is topology.FORWARD_PRIORITY
    assert state.PREREQ_OF is topology.PREREQ_OF
    assert state.SKILL_OF is topology.SKILL_OF
    assert state._result_path is topology._result_path
    assert state.is_dag_ancestor is topology.is_dag_ancestor
