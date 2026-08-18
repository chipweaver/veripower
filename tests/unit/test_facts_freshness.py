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
    # Validity condition 4: hand-editing the rule's own output invalidates its proof.
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


def _sign_off_everything(module):
    """Construct: for every rule in FORWARD_PRIORITY (the 8 stages), one
    dispatch+outcome pair carrying a passing same-name proof with empty
    inputs/outputs (so proof_valid has nothing on disk to falsify) and an
    oracle matching that rule's declared rules.RULES[rule].oracle (ref, grade);
    then the human `signoff` event that is the predicate's first conjunct.
    Enough to make every stage cell read "valid" and signed_off hold."""
    for rule_name in rules.FORWARD_PRIORITY:
        rule = rules.RULES[rule_name]
        facts.append_event(
            module,
            {
                "type": "dispatch",
                "rule": rule_name,
                "run": 1,
                "workdir": "w",
                "inputs": {},
                "params": {},
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
    facts.append_event(
        module, {"type": "signoff", "provenance": "u", "reason": "ship it"}, TS
    )


def test_signed_off_regresses_on_reopen(tmp_path, monkeypatch):
    # Reopen of any pin flips signed_off back. (The hand-edit half of the same
    # invariant needs on-disk outputs this empty-outputs fixture cannot carry — it is
    # covered by test_schedule.py::test_signed_off_regresses_on_hand_edit.)
    monkeypatch.chdir(tmp_path)
    _sign_off_everything("m")  # helper: 8 pass proofs + the human signoff event
    evs = facts.read_events("m")
    assert facts.signed_off("m", evs) is True
    facts.append_event(
        "m", {"type": "reopen", "pin_ref": "spec-review", "reason": "revoke"}, TS
    )
    assert facts.signed_off("m", facts.read_events("m")) is False


def test_hand_editing_canonical_result_json_invalidates_proof(tmp_path, monkeypatch):
    # The canonical result.json is in the rule's OWN output binding, so hand-
    # editing it (coverage-inflation / "灌水即作废") invalidates the proof via condition 4 —
    # exactly like tampering any other promoted output. End-to-end freshness assertion.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    rjrel = "Design/specification/result.json"
    _write("m", rjrel, '{"status": "pass"}')
    bm = _fp("m", "brainstorm.md")
    rj = _fp("m", rjrel)
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"brainstorm.md": bm},
            "params": {},
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
            "outputs": {rjrel: rj},
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"brainstorm.md": bm},
                    "oracle": {"ref": "spec-review", "grade": "proposed"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    assert facts.proof_valid("m", facts.read_events("m"), "specification")
    _write(
        "m", rjrel, '{"status": "pass", "coverage": "INFLATED"}'
    )  # 灌水: edit result.json
    assert not facts.proof_valid("m", facts.read_events("m"), "specification")


def _spec_run(module, run, *, oracle_grade="human"):
    """Dispatch+pass specification run N with brainstorm on disk; returns nothing."""
    bm = _fp(module, "brainstorm.md")
    facts.append_event(
        module,
        {
            "type": "dispatch",
            "rule": "specification",
            "run": run,
            "workdir": "w",
            "inputs": {"brainstorm.md": bm},
            "params": {},
        },
        TS,
    )
    facts.append_event(
        module,
        {
            "type": "outcome",
            "rule": "specification",
            "run": run,
            "verdict": "pass",
            "outputs": {},
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"brainstorm.md": bm},
                    "oracle": {"ref": "spec-review", "grade": oracle_grade},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )


def test_re_reap_after_reopen_does_not_resurrect_proof(tmp_path, monkeypatch):
    # Reopen withdraws trust; a bare RE-REAP (re-reading the same run, no re-execution,
    # no re-pin) must NOT resurrect the proof. Condition 3 anchors on the run's DISPATCH.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _spec_run("m", 1)  # dispatch(run1) + outcome(run1)
    facts.append_event(
        "m",
        {
            "type": "pin",
            "oracle_ref": "spec-review",
            "content_fingerprint": "sha256:x",
            "provenance": "p",
            "reason": "endorse",
        },
        TS,
    )
    assert facts.proof_valid("m", facts.read_events("m"), "specification")
    facts.append_event(
        "m", {"type": "reopen", "pin_ref": "spec-review", "reason": "revoke"}, TS
    )
    assert not facts.proof_valid("m", facts.read_events("m"), "specification")
    # RE-REAP run 1: append a later outcome for the SAME run (no new dispatch, no re-pin)
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
                    "inputs": {"brainstorm.md": _fp("m", "brainstorm.md")},
                    "oracle": {"ref": "spec-review", "grade": "proposed"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    assert not facts.proof_valid(
        "m", facts.read_events("m"), "specification"
    )  # STAYS invalid


def test_repin_after_reopen_restores_validity(tmp_path, monkeypatch):
    # Companion: a genuine re-pin (human re-endorses) after reopen DOES restore validity —
    # the second conjunct (no live pin) is then false. The legitimate pin/regrade path lives.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _spec_run("m", 1)
    facts.append_event(
        "m",
        {
            "type": "pin",
            "oracle_ref": "spec-review",
            "content_fingerprint": "sha256:x",
            "provenance": "p",
            "reason": "endorse",
        },
        TS,
    )
    facts.append_event(
        "m", {"type": "reopen", "pin_ref": "spec-review", "reason": "revoke"}, TS
    )
    assert not facts.proof_valid("m", facts.read_events("m"), "specification")
    facts.append_event(
        "m",
        {
            "type": "pin",
            "oracle_ref": "spec-review",
            "content_fingerprint": "sha256:y",
            "provenance": "p",
            "reason": "re-endorse",
        },
        TS,
    )
    assert facts.proof_valid(
        "m", facts.read_events("m"), "specification"
    )  # re-pin restores


def test_fresh_dispatch_after_reopen_is_valid(tmp_path, monkeypatch):
    # Companion: a genuine re-execution (new dispatch AFTER the reopen, then reaped) is
    # valid — its dispatch post-dates the reopen, so condition 3 does not fire.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _spec_run("m", 1)
    facts.append_event(
        "m",
        {
            "type": "pin",
            "oracle_ref": "spec-review",
            "content_fingerprint": "sha256:x",
            "provenance": "p",
            "reason": "endorse",
        },
        TS,
    )
    facts.append_event(
        "m", {"type": "reopen", "pin_ref": "spec-review", "reason": "revoke"}, TS
    )
    _spec_run(
        "m", 2, oracle_grade="proposed"
    )  # fresh dispatch(run2)+outcome AFTER the reopen
    assert facts.proof_valid("m", facts.read_events("m"), "specification")


def test_stale_inputs_returns_changed_declared_inputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "Design/specification/design.md", "d1")
    _write("m", "Design/specification/manifest.json", "{}")
    _write("m", "Design/specification/child_a.md", "a1")
    recorded = {
        "Design/specification/design.md": _fp("m", "Design/specification/design.md"),
        "Design/specification/manifest.json": _fp(
            "m", "Design/specification/manifest.json"
        ),
        "Design/specification/child_a.md": _fp("m", "Design/specification/child_a.md"),
    }
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "rtl-design",
            "run": 1,
            "workdir": "w",
            "inputs": recorded,
            "params": {},
        },
        TS,
    )
    facts.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "rtl-design",
            "run": 1,
            "verdict": "pass",
            "outputs": {},
            "proofs": [
                {
                    "name": "rtl-design",
                    "verdict": "pass",
                    "inputs": recorded,
                    "oracle": {"ref": "semantic-review", "grade": "proposed"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    evs = facts.read_events("m")
    assert facts.stale_inputs("m", evs, "rtl-design") == []  # nothing drifted yet
    _write("m", "Design/specification/child_a.md", "a2-changed")  # one input drifts
    assert facts.stale_inputs("m", evs, "rtl-design") == [
        "Design/specification/child_a.md"
    ]


def test_stale_inputs_empty_without_prior_outcome(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert facts.stale_inputs("m", [], "rtl-design") == []


def test_proof_none_rule_available_despite_invalid_upstream(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # no upstream outcomes at all → normal rules unavailable, but a proof=None rule is available
    evs = (
        facts.read_events("m")
        if (facts.module_root("m") / "events.jsonl").exists()
        else []
    )
    assert facts.rule_available("m", evs, "simulation-triage") is True
