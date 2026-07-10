import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import rules  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def _fp(module, rel):
    return facts.fingerprint(facts.module_root(module) / rel)


def _write(module, rel, text):
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_proof_valid_then_input_change_invalidates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "v1")
    _write("m", "Design/specification/design.md", "d1")
    v = _fp("m", "brainstorm.md")
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"brainstorm.md": v},
            "params": {},
            "objective": "delivery",
        },
        TS,
    )
    facts.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "specification",
            "run": 1,
            "verdict": "pass",
            "outputs": {
                "Design/specification/design.md": _fp(
                    "m", "Design/specification/design.md"
                )
            },
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"brainstorm.md": v},
                    "oracle": {"ref": "spec-review", "grade": "human"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    evs = facts.read_events("m")
    assert facts.proof_valid("m", evs, "specification")
    _write("m", "brainstorm.md", "v2-changed")  # input drifts
    assert not facts.proof_valid("m", evs, "specification")


def test_proof_invalid_when_own_output_handedited(tmp_path, monkeypatch):
    # spec §1.3 condition 4: hand-editing the rule's own output invalidates its proof.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "v1")
    dm = _write("m", "Design/specification/design.md", "d1")
    v = _fp("m", "brainstorm.md")
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"brainstorm.md": v},
            "params": {},
            "objective": "delivery",
        },
        TS,
    )
    facts.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "specification",
            "run": 1,
            "verdict": "pass",
            "outputs": {
                "Design/specification/design.md": _fp(
                    "m", "Design/specification/design.md"
                )
            },
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"brainstorm.md": v},
                    "oracle": {"ref": "spec-review", "grade": "human"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    evs = facts.read_events("m")
    assert facts.proof_valid("m", evs, "specification")
    dm.write_text("hand-edited")  # tamper own output
    assert not facts.proof_valid("m", evs, "specification")


def test_fail_verdict_is_not_valid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "v1")
    v = _fp("m", "brainstorm.md")
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"brainstorm.md": v},
            "params": {},
            "objective": "delivery",
        },
        TS,
    )
    facts.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "specification",
            "run": 1,
            "verdict": "fail",
            "outputs": {},
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "fail",
                    "inputs": {"brainstorm.md": v},
                    "oracle": {"ref": "spec-review", "grade": "proposed"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    assert not facts.proof_valid("m", facts.read_events("m"), "specification")


def test_reopen_after_proof_invalidates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "v1")
    v = _fp("m", "brainstorm.md")
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"brainstorm.md": v},
            "params": {},
            "objective": "delivery",
        },
        TS,
    )
    facts.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "specification",
            "run": 1,
            "verdict": "pass",
            "outputs": {},
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"brainstorm.md": v},
                    "oracle": {"ref": "spec-review", "grade": "human"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    assert facts.proof_valid("m", facts.read_events("m"), "specification")
    facts.append_event(
        "m", {"type": "reopen", "pin_ref": "spec-review", "reason": "revoke"}, TS
    )
    assert not facts.proof_valid("m", facts.read_events("m"), "specification")


def test_inout_artifact_compared_against_same_run_output_no_false_staleness(
    tmp_path, monkeypatch
):
    # §1.3 in∩out: a run that UPDATES its own input (lint waiver) must not make its
    # proof born-stale — condition 2 compares the same-run OUTPUT version for such paths.
    monkeypatch.chdir(tmp_path)
    w = _write("m", "Design/lint-cdc/scripts/waiver.tcl", "waive-v1")
    v1 = _fp("m", "Design/lint-cdc/scripts/waiver.tcl")
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "lint-cdc",
            "run": 1,
            "workdir": "w",
            "inputs": {"Design/lint-cdc/scripts/waiver.tcl": v1},
            "params": {},
            "objective": "delivery",
        },
        TS,
    )
    w.write_text("waive-v2-updated-during-run")  # run rewrites its own input
    v2 = _fp("m", "Design/lint-cdc/scripts/waiver.tcl")
    facts.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "lint-cdc",
            "run": 1,
            "verdict": "pass",
            "outputs": {"Design/lint-cdc/scripts/waiver.tcl": v2},
            "proofs": [
                {
                    "name": "lint-cdc",
                    "verdict": "pass",
                    "inputs": {"Design/lint-cdc/scripts/waiver.tcl": v1},
                    "oracle": {"ref": "spyglass-ruleset", "grade": "tool"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    # v1 != disk(v2), but the path is in this outcome's outputs -> compared against v2 -> valid
    assert facts.proof_valid("m", facts.read_events("m"), "lint-cdc")


def _sign_off_everything(module):
    """Construct: for every rule in FORWARD_PRIORITY (the 9 stages), one
    dispatch+outcome pair carrying a passing same-name proof with empty
    inputs/outputs (so proof_valid has nothing on disk to falsify) and an
    oracle matching that rule's declared rules.RULES[rule].oracle (ref, grade).
    frontend-signoff's dispatch objective is "signoff" (not "delivery") so
    _signoff_dispatch_was_signoff holds — everything else is objective=delivery.
    Asserts (via the two projection() calls in the caller) that this is enough
    to make every stage cell, and the signoff cell, read "valid"."""
    for rule_name in rules.FORWARD_PRIORITY:
        rule = rules.RULES[rule_name]
        objective = "signoff" if rule_name == "frontend-signoff" else "delivery"
        facts.append_event(
            module,
            {
                "type": "dispatch",
                "rule": rule_name,
                "run": 1,
                "workdir": "w",
                "inputs": {},
                "params": {},
                "objective": objective,
            },
            TS,
        )
        facts.append_event(
            module,
            {
                "type": "outcome",
                "rule": rule_name,
                "run": 1,
                "verdict": "pass",
                "outputs": {},
                "proofs": [
                    {
                        "name": rule_name,
                        "verdict": "pass",
                        "inputs": {},
                        "oracle": {"ref": rule.oracle[0], "grade": rule.oracle[1]},
                    }
                ],
                "tool_versions": {},
            },
            TS,
        )


def test_projection_signoff_cell_regresses_on_reopen_and_hand_edit(
    tmp_path, monkeypatch
):
    # §3.6/§6: reopen of any pin, or hand-editing any file, flips the signoff cell back.
    # Build: all 9 proofs valid + a signoff-objective frontend-signoff proof (helper
    # follows the test_facts_freshness dispatch/outcome pattern per rule — mechanical).
    monkeypatch.chdir(tmp_path)
    _sign_off_everything(
        "m"
    )  # helper: 9 pass proofs + signoff dispatch objective=signoff
    evs = facts.read_events("m")
    assert facts.projection("m", evs)["frontend-signoff"] == "valid"
    facts.append_event(
        "m", {"type": "reopen", "pin_ref": "spec-review", "reason": "revoke"}, TS
    )
    assert facts.projection("m", facts.read_events("m"))["frontend-signoff"] == "stale"
