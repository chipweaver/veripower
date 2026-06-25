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


# ── finalize: build_result + gamma-floor args (host = validate_scaffold) ─────
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "simulation-plan" / "scripts"))
import validate_scaffold as vs  # noqa: E402

_REVIEW_CLEAR = {
    "schema_version": 1,
    "stage": "simulation-plan",
    "module": "tpu_top",
    "reviewed_testpoints": ["TP-1"],
    "verdict": "ok",
    "has_critical": False,
    "findings": [],
}


def _plan_md(features=("F-01", "F-02")):
    rows = "\n".join(f"| TP-{i} | {f} | ... |" for i, f in enumerate(features))
    return f"# Plan\n## 3. Testpoints Table\n| id | feature | desc |\n|---|---|---|\n{rows}\n"


def _finalize_workdir(tmp_path, *, scaffold=None, plan_md=None, review=_REVIEW_CLEAR):
    wd = tmp_path
    (wd / "scaffold-specification.json").write_text(json.dumps(scaffold or GOOD))
    (wd / "verification-plan.md").write_text(plan_md or _plan_md())
    (wd / "plan-review.json").write_text(json.dumps(review))
    return wd


def test_build_result_pass_lean_shape(tmp_path):
    wd = _finalize_workdir(tmp_path)
    assert (
        vs.build_result(wd, module="tpu_top", waived=None, status=None, revision=None)
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "simulation-plan",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    # GOOD has 2 agents / 1 sequence / 1 test / 1 testpoint / 1 power_scenario
    assert ss["testpoint_count"] == 1 and ss["power_scenario_count"] == 1
    assert ss["feature_count"] == 2  # distinct F-NN in the plan md
    assert ss["scaffold_summary"] == {
        "agent_count": 2,
        "sequence_count": 1,
        "test_count": 1,
    }
    assert ss["plan_adequacy_gate"] == {"gate": "clear", "flagged": [], "must_ack": []}
    # lean shape: no narration when not passed; no fail_reason on pass
    assert "revision" not in ss and "fail_reason" not in ss


def test_build_result_fail_on_user_reject(tmp_path):
    wd = _finalize_workdir(tmp_path)  # gate clears, but the user rejected
    assert (
        vs.build_result(wd, module="tpu_top", waived=None, status="fail", revision=None)
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["fail_reason"] == "user rejected plan"
    assert "feature_count" not in env["stage_specific"]  # fail shape is lean


def test_build_result_gate_trip_unwaived_is_fail(tmp_path):
    wd = _finalize_workdir(
        tmp_path,
        review={
            **_REVIEW_CLEAR,
            "verdict": "concerns",
            "has_critical": True,
            "findings": [
                {
                    "tp_id": "TP-X",
                    "lens": "coverage",
                    "severity": "critical",
                    "location": "§3",
                    "summary": "uncovered spec block",
                }
            ],
        },
    )
    assert (
        vs.build_result(wd, module="tpu_top", waived=None, status=None, revision=None)
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["plan_adequacy_gate"]["gate"] == "trip"


def test_build_result_gate_trip_fully_waived_is_pass(tmp_path):
    # every flagged item waived by the human → pass (Step-5 approve precondition)
    wd = _finalize_workdir(
        tmp_path,
        review={
            **_REVIEW_CLEAR,
            "verdict": "concerns",
            "has_critical": True,
            "findings": [
                {
                    "tp_id": "TP-X",
                    "lens": "coverage",
                    "severity": "critical",
                    "location": "§3",
                    "summary": "uncovered spec block",
                }
            ],
        },
    )
    waived = [
        {
            "tp_id": "TP-X",
            "lens": "coverage",
            "location": "§3",
            "classification": "accepted-risk",
            "reason": "terminal accept — no downstream re-check",
        }
    ]
    assert (
        vs.build_result(
            wd,
            module="tpu_top",
            waived=waived,
            status=None,
            revision="rev 0.2 (rework r1): waived TP-X",
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "pass"
    assert ss["plan_adequacy_gate"]["waived"] == waived
    assert (
        ss["revision"] == "rev 0.2 (rework r1): waived TP-X"
    )  # gamma-floor narration carried


def test_finalize_cli_does_not_break_legacy_validate_cli(tmp_path):
    # the legacy bare-flag invocation still validates (no subcommand) — back-compat guard
    proc = _run(tmp_path, GOOD)
    assert proc.returncode == 0 and "OK" in proc.stdout


# ── feature_count derivation (distinct F-NN in verification-plan.md) ─────────
def test_count_features_distinct():
    md = "| TP-1 | F-01 | x |\n| TP-2 | F-01 | y |\n| TP-3 | F-02 | z |\n"
    assert vs.count_features(md) == 2  # F-01 counted once


def test_count_features_zero_when_absent():
    assert vs.count_features("# Plan\nno feature ids here\n") == 0


def test_count_features_ignores_non_fnn_tokens():
    assert (
        vs.count_features("prose mentions F- and Frame-01 and F-12\n") == 1
    )  # only F-12


# ── artifacts[] enumeration (fixed 3-entry set, present-only, no self-listing) ─
def test_enumerate_artifacts_fixed_set_with_kinds(tmp_path):
    wd = _finalize_workdir(tmp_path)
    arts = vs.enumerate_artifacts(wd)
    by_path = {a["path"]: a.get("kind") for a in arts}
    assert by_path == {
        "verification-plan.md": "plan",
        "scaffold-specification.json": "scaffold",
        "plan-review.json": "plan-review",
    }
    assert "result.json" not in by_path
    assert all((wd / p).is_file() for p in by_path)


# ── golden: lean shape + schema, against the real tpu_top run ────────────────
from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"


def _validate_envelope(env: dict) -> None:
    # Inline Registry (NOT the frontend-signoff-bound _validate_envelope): validate the
    # in-memory envelope against {envelope schema + simulation-plan result.schema} via Registry.
    env_schema = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (ROOT / "skills/simulation-plan/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        _ENVELOPE_URI, Resource.from_contents(env_schema)
    )
    Draft202012Validator(stage_schema, registry=registry).validate(env)


def test_golden_lean_against_real_tpu_top(tmp_path):
    import shutil

    FIX = Path(__file__).resolve().parent / "fixtures" / "simulation-plan-tpu_top"
    wd = tmp_path / "simulation-plan"
    shutil.copytree(FIX, wd)
    rev = "rev 0.3 (rework r2): added apb_weight_load precondition to T-04 + T-07"
    assert (
        vs.build_result(wd, module="tpu_top", waived=None, status=None, revision=rev)
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "pass"
    # counts — EXACT to the real run (asic/tpu_top result.json:11-19)
    assert ss["feature_count"] == 5  # distinct F-01..F-05 in verification-plan.md
    assert ss["testpoint_count"] == 18  # len(scaffold.testpoints)
    assert ss["power_scenario_count"] == 9  # len(scaffold.power_scenarios)
    assert ss["scaffold_summary"] == {
        "agent_count": 2,
        "sequence_count": 9,
        "test_count": 7,
    }
    assert ss["plan_adequacy_gate"] == {"gate": "clear", "flagged": [], "must_ack": []}
    assert ss["revision"] == rev  # gamma-floor narration carried through
    # artifacts: the 3-entry set (plan-review.json staged → promoted)
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {
        "verification-plan.md",
        "scaffold-specification.json",
        "plan-review.json",
    }
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")
    _validate_envelope(env)
