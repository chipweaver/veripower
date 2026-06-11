"""Tests for validate_scaffold.py — sim-plan gate: structural (jsonschema) + semantic cross-ref."""

import copy
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/simulation-plan/scripts/validate_scaffold.py"

# Canonical, post-materialize, fully-valid scaffold (agents carry materialize-injected
# interface/transaction). Built from the SKILL contract, NOT from any legacy disk artifact.
GOOD = {
    "module": "m",
    "top": "m_top",
    "agents": [
        {
            "name": "drv",
            "mode": "active",
            "interface_groups": ["cfg"],
            "interface": {"signals": [{"name": "wdata", "width": 32}]},
            "transaction": {
                "fields": [
                    {"name": "wdata", "width": 32, "type": "logic", "rand": True}
                ]
            },
        },
        {
            "name": "obs",
            "mode": "passive",
            "interface_groups": ["stat"],
            "interface": {"signals": [{"name": "rdata", "width": 32}]},
            "transaction": {
                "fields": [
                    {"name": "rdata", "width": 32, "type": "logic", "rand": True}
                ]
            },
        },
    ],
    "sequences": [{"name": "smoke", "agent": "drv", "desc": "smoke"}],
    "tests": [{"name": "t_smoke", "feature": "F1", "test_id": "T1", "seqs": ["smoke"]}],
    "rm": {"name": "m_rm", "inports": ["m_drv_txn"]},
    "scoreboard": {"name": "m_sb", "compare_txn": "m_obs_txn"},
    "primary_clock": {"dut_port_name": "clk", "period_ns": "10.0"},
    "reset": {"dut_port_name": "rst_n"},
    "testpoints": [
        {
            "id": "TP-1",
            "bins": ["a"],
            "covers": ["CHK-0"],
            "inlined_check_hints": [
                {"check_id": "CHK-0", "implementation_detail": "x"}
            ],
        }
    ],
    "power_scenarios": [{"id": "S1", "sequence_ref": "smoke", "clock_state": "on"}],
}


def _run(tmp_path, scaffold, check=True, plan_data=None):
    sc = tmp_path / "scaffold-specification.json"
    sc.write_text(json.dumps(scaffold))
    pd = tmp_path / "plan-data.json"
    if plan_data is None:
        plan_data = {
            "check_hints": [{"check_id": "CHK-0"}]
        }  # matches GOOD.testpoints covers
    pd.write_text(json.dumps(plan_data))
    return subprocess.run(
        ["python3", str(SCRIPT), "--scaffold", str(sc), "--plan-data", str(pd)],
        capture_output=True,
        text=True,
        check=check,
    )


def test_good_scaffold_passes(tmp_path):
    proc = _run(tmp_path, GOOD)
    assert proc.returncode == 0 and "OK" in proc.stdout


def test_injected_interface_transaction_tolerated(tmp_path):
    # GOOD already carries materialize-injected interface/transaction. addP:false must not reject them.
    assert _run(tmp_path, GOOD).returncode == 0


# ---- structural ----
def test_compare_txn_list_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["scoreboard"]["compare_txn"] = ["a", "b"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "compare_txn" in proc.stderr


def test_inports_string_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["rm"]["inports"] = "m_drv_txn"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "inports" in proc.stderr


def test_seqs_string_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["tests"][0]["seqs"] = "smoke"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "seqs" in proc.stderr


def test_mode_non_enum_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"][0]["mode"] = "master"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "mode" in proc.stderr


def test_mode_missing_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    del s["agents"][0]["mode"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "mode" in proc.stderr


def test_missing_interface_groups_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    del s["agents"][0]["interface_groups"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "interface_groups" in proc.stderr


def test_agent_extra_key_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"][0]["drive_signals"] = ["wdata"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0  # additionalProperties:false on agents[]


def test_missing_primary_clock_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    del s["primary_clock"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "primary_clock" in proc.stderr


# ---- semantic ----
def test_compare_txn_unknown_agent_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["scoreboard"]["compare_txn"] = "m_nope_txn"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "compare_txn" in proc.stderr


def test_compare_txn_omitted_single_agent_passes(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"] = [s["agents"][0]]  # single agent: drv
    s["sequences"] = [{"name": "smoke", "agent": "drv"}]
    s["rm"]["inports"] = ["m_drv_txn"]
    del s["scoreboard"]["compare_txn"]
    assert _run(tmp_path, s).returncode == 0


def test_compare_txn_omitted_multi_agent_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    del s["scoreboard"]["compare_txn"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "compare_txn" in proc.stderr  # option-c


def test_inports_unknown_agent_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["rm"]["inports"] = ["m_ghost_txn"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "inports" in proc.stderr


def test_seqs_unknown_sequence_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["tests"][0]["seqs"] = ["ghost"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "seqs" in proc.stderr


def test_sequence_agent_unknown_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["sequences"][0]["agent"] = "ghost"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "agent" in proc.stderr


def test_sequence_ref_unknown_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["power_scenarios"][0]["sequence_ref"] = "ghost"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "sequence_ref" in proc.stderr


def test_sequence_ref_non_string_fails(tmp_path):
    # A non-string sequence_ref must fail structurally (clean message), not crash with a
    # TypeError in the semantic membership check (power_scenarios items are addP:true).
    s = copy.deepcopy(GOOD)
    s["power_scenarios"][0]["sequence_ref"] = ["smoke"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "sequence_ref" in proc.stderr


def test_duplicate_agent_name_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"][1]["name"] = "drv"  # both agents now named "drv"
    s["scoreboard"]["compare_txn"] = (
        "m_drv_txn"  # keep refs resolving so only the dup fires
    )
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "duplicated" in proc.stderr


def test_skipped_checks_shape_validated(tmp_path):
    """skipped_checks[] entries require check_id + reason; a malformed entry fails structurally."""
    s = copy.deepcopy(GOOD)
    s["skipped_checks"] = [{"check_id": "CHK-9"}]  # missing 'reason'
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "reason" in proc.stderr


# ---- coverage matrix ----
def test_coverage_uncovered_check_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["testpoints"] = [
        {
            "id": "TP-0",
            "covers": ["CHK-00"],
            "inlined_check_hints": [
                {"check_id": "CHK-00", "implementation_detail": "x"}
            ],
        }
    ]
    proc = _run(
        tmp_path,
        s,
        check=False,
        plan_data={"check_hints": [{"check_id": "CHK-00"}, {"check_id": "CHK-01"}]},
    )
    assert (
        proc.returncode != 0 and "uncovered" in proc.stderr and "CHK-01" in proc.stderr
    )


def test_coverage_skip_passes(tmp_path):
    s = copy.deepcopy(GOOD)
    s["testpoints"] = [
        {
            "id": "TP-0",
            "covers": ["CHK-00"],
            "inlined_check_hints": [
                {"check_id": "CHK-00", "implementation_detail": "x"}
            ],
        }
    ]
    s["skipped_checks"] = [{"check_id": "CHK-01", "reason": "lint-only gate"}]
    proc = _run(
        tmp_path,
        s,
        plan_data={"check_hints": [{"check_id": "CHK-00"}, {"check_id": "CHK-01"}]},
    )
    assert proc.returncode == 0


def test_coverage_dangling_covers_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["testpoints"] = [
        {
            "id": "TP-0",
            "covers": ["CHK-00", "CHK-99"],
            "inlined_check_hints": [
                {"check_id": "CHK-00", "implementation_detail": "x"}
            ],
        }
    ]
    proc = _run(
        tmp_path, s, check=False, plan_data={"check_hints": [{"check_id": "CHK-00"}]}
    )
    assert (
        proc.returncode != 0
        and "unknown check_id" in proc.stderr
        and "CHK-99" in proc.stderr
    )


def test_coverage_fully_covered_passes(tmp_path):
    s = copy.deepcopy(GOOD)
    s["testpoints"] = [
        {
            "id": "TP-0",
            "covers": ["CHK-00", "CHK-01"],
            "inlined_check_hints": [
                {"check_id": "CHK-00", "implementation_detail": "x"},
                {"check_id": "CHK-01", "implementation_detail": "y"},
            ],
        }
    ]
    proc = _run(
        tmp_path,
        s,
        plan_data={"check_hints": [{"check_id": "CHK-00"}, {"check_id": "CHK-01"}]},
    )
    assert proc.returncode == 0
