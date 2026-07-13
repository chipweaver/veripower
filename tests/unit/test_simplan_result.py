"""Tests for the simplan finalize verb — build_result + human-gate args + count/enumerate."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation-plan" / "scripts"))
from simplan import result as vs  # noqa: E402

# GOOD : copy VERBATIM from the pre-consolidation validate-scaffold test (the post-materialize
# canonical scaffold). Reproduced here so the file is self-contained.
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
    )  # human-gate narration carried


# ── feature_count derivation (distinct F-NN in the §3 Testpoints section) ────
def test_count_features_distinct():
    md = (
        "## 3. Testpoints Table\n"
        "| TP-1 | F-01 | x |\n| TP-2 | F-01 | y |\n| TP-3 | F-02 | z |\n"
    )
    assert vs.count_features(md) == 2  # F-01 counted once


def test_count_features_zero_when_absent():
    assert vs.count_features("# Plan\nno feature ids here\n") == 0


def test_count_features_ignores_non_fnn_tokens():
    md = "## 3. Testpoints Table\nprose mentions F- and Frame-01 and F-12\n"
    assert vs.count_features(md) == 1  # only F-12


def test_count_features_ignores_s5_revision_mentions():
    # an F-NN cited only in the §5 revision note (e.g. a dropped testpoint's
    # attribution) must not inflate the count across reworks
    md = (
        "## 3. Testpoints Table\n| TP-1 | F-01 | x |\n"
        "## 5. Revision Summary\nremoved over-spec testpoint for F-99\n"
    )
    assert vs.count_features(md) == 1


def test_count_features_not_shadowed_by_decoy_heading():
    # a heading merely MENTIONING testpoints must not capture the section — the
    # pattern anchors to the start of the heading text
    md = (
        "## 1.3 Overview of Testpoints strategy\nprose citing F-77\n"
        "## 3. Testpoints Table\n| TP-1 | F-01 | x |\n| TP-2 | F-02 | y |\n"
    )
    assert vs.count_features(md) == 2  # F-01/F-02, not F-77


def test_count_features_case_insensitive_heading():
    md = "## 3. TESTPOINTS TABLE\n| TP-1 | F-01 | x |\n"
    assert vs.count_features(md) == 1


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
    assert ss["revision"] == rev  # human-gate narration carried through
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


# ── net-new: finalize-wrapper exit-code BLOCKED semantics (F6) ──
def test_finalize_blocked_on_bad_waived_json(tmp_path):
    # malformed --waived JSON → exit 2 BLOCKED (never a status=fail result.json)
    wd = tmp_path
    (wd / "scaffold-specification.json").write_text(json.dumps(GOOD))
    (wd / "verification-plan.md").write_text("# Plan\n| TP-1 | F-01 | x |\n")
    (wd / "plan-review.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": "simulation-plan",
                "module": "m",
                "reviewed_testpoints": ["TP-1"],
                "verdict": "ok",
                "has_critical": False,
                "findings": [],
            }
        )
    )
    assert (
        vs.finalize(wd, "m", waived_json="{not json", status=None, revision=None) == 2
    )
    assert not (wd / "result.json").exists()


def test_finalize_blocked_on_internal_raise(tmp_path):
    # missing scaffold-specification.json → build_result raises → caught → exit 2 BLOCKED
    assert vs.finalize(tmp_path, "m", waived_json=None, status=None, revision=None) == 2


# ── early-fail entry (--fail-reason): routable fail, present-only carry ──────
def test_finalize_earlyfail_empty_workdir(tmp_path):
    # Step-1/2 early fail: nothing generated yet — finalize must still write a
    # routable fail envelope (never BLOCKED, never a hand-assembled envelope)
    rc = vs.finalize(
        tmp_path,
        "m",
        waived_json=None,
        status="fail",
        revision=None,
        fail_reason="external reference missing: Design/specification/design.md",
    )
    assert rc == 0
    env = json.loads((tmp_path / "result.json").read_text())
    assert env["status"] == "fail"
    ss = env["stage_specific"]
    assert ss["fail_reason"].startswith("external reference missing")
    assert "plan_adequacy_gate" not in ss  # legitimate pre-Step-4 fail
    assert env["artifacts"] == []


def test_finalize_earlyfail_seeded_workdir_carries_products(tmp_path):
    # on a seeded rework workdir the present-only enumeration carries the prior
    # products, so a promoted early fail cannot GC canonical down to a hollow view
    (tmp_path / "verification-plan.md").write_text("PLAN", encoding="utf-8")
    (tmp_path / "scaffold-specification.json").write_text("{}", encoding="utf-8")
    rc = vs.finalize(
        tmp_path,
        "m",
        waived_json=None,
        status="fail",
        revision=None,
        fail_reason="failing_result not readable: /x/result.json",
    )
    assert rc == 0
    env = json.loads((tmp_path / "result.json").read_text())
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {"verification-plan.md", "scaffold-specification.json"}
    assert "plan_adequacy_gate" not in env["stage_specific"]


def test_finalize_blocked_on_empty_fail_reason(tmp_path):
    rc = vs.finalize(
        tmp_path, "m", waived_json=None, status="fail", revision=None, fail_reason="  "
    )
    assert rc == 2
    assert not (tmp_path / "result.json").exists()


def test_fail_reason_without_status_fail_is_blocked(tmp_path):
    # an unpaired --fail-reason is a caller slip about to invert a failure into a
    # computed pass — refused loudly, never silently discarded
    wd = _finalize_workdir(tmp_path)
    rc = vs.finalize(
        wd,
        "m",
        waived_json=None,
        status=None,
        revision=None,
        fail_reason="user rejected plan",
    )
    assert rc == 2
    assert not (wd / "result.json").exists()


def test_bare_status_fail_without_review_is_blocked(tmp_path):
    # a user reject can only follow Step 4/5 — with no judged record on disk a bare
    # --status fail would fabricate a human rejection that never happened
    (tmp_path / "verification-plan.md").write_text("PLAN", encoding="utf-8")
    rc = vs.finalize(tmp_path, "m", waived_json=None, status="fail", revision=None)
    assert rc == 2
    assert not (tmp_path / "result.json").exists()


def test_waived_on_fail_without_review_is_blocked(tmp_path):
    # a well-formed waiver must never silently vanish from the promoted fail
    waived = json.dumps(
        [
            {
                "tp_id": "TP-X",
                "lens": "coverage",
                "location": "§3",
                "classification": "accepted-risk",
                "reason": "operator judgment",
            }
        ]
    )
    rc = vs.finalize(
        tmp_path, "m", waived_json=waived, status="fail", revision=None, fail_reason="x"
    )
    assert rc == 2
    assert not (tmp_path / "result.json").exists()


def test_fail_with_corrupt_plan_review_is_blocked(tmp_path):
    # presence decides: an absent record is a legitimate early fail, but a
    # present-and-corrupt one must surface (exit 2), not silently drop the gate
    (tmp_path / "plan-review.json").write_text("{not json", encoding="utf-8")
    rc = vs.finalize(
        tmp_path, "m", waived_json=None, status="fail", revision=None, fail_reason="x"
    )
    assert rc == 2
    assert not (tmp_path / "result.json").exists()


def test_fail_with_present_review_carries_gate(tmp_path):
    # user reject after Step 4: the judged gate travels with the promoted fail
    wd = _finalize_workdir(tmp_path)
    rc = vs.finalize(wd, "m", waived_json=None, status="fail", revision=None)
    assert rc == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["stage_specific"]["fail_reason"] == "user rejected plan"
    assert env["stage_specific"]["plan_adequacy_gate"]["gate"] == "clear"


# ── --waived content validation (human trust record, no placeholder laundering) ──
def test_finalize_blocked_on_waived_missing_reason(tmp_path):
    wd = _finalize_workdir(tmp_path)
    bad = json.dumps(
        [{"tp_id": "TP-X", "lens": "coverage", "classification": "accepted-risk"}]
    )
    assert vs.finalize(wd, "m", waived_json=bad, status=None, revision=None) == 2
    assert not (wd / "result.json").exists()


def test_finalize_blocked_on_waived_bad_classification(tmp_path):
    wd = _finalize_workdir(tmp_path)
    bad = json.dumps(
        [
            {
                "tp_id": "TP-X",
                "lens": "coverage",
                "classification": "acceptable",  # not in the enum
                "reason": "looks fine",
            }
        ]
    )
    assert vs.finalize(wd, "m", waived_json=bad, status=None, revision=None) == 2
    assert not (wd / "result.json").exists()
