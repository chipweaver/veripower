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


def test_self_produced_inout_input_never_self_locks(tmp_path, monkeypatch):
    # F1 / spec §2 自产输入豁免: a rule's self-produced in∩out input (lint-cdc waiver.tcl)
    # must NEVER make the rule un-dispatchable. After a passing lint run recorded waiver.tcl
    # as an output, condition 4 invalidates that proof if the waiver is EDITED or DELETED
    # out-of-band — so lint must be re-dispatched, which requires it stay `input_available`.
    # "无 outcome 或文件缺失 = 冷启动，照常可派发" — and the same holds for an edited waiver,
    # else the proof-invalidation immediately locks the rule (exactly the self-lock forbidden).
    monkeypatch.chdir(tmp_path)
    w = "Design/lint-cdc/scripts/waiver.tcl"
    _write("m", w, "waive-v1")
    v1 = _fp("m", w)
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "lint-cdc",
            "run": 1,
            "workdir": "w",
            "inputs": {w: v1},
            "params": {},
            "objective": "delivery",
        },
        TS,
    )
    facts.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "lint-cdc",
            "run": 1,
            "verdict": "pass",
            "outputs": {w: v1},
            "proofs": [
                {
                    "name": "lint-cdc",
                    "verdict": "pass",
                    "inputs": {w: v1},
                    "oracle": {"ref": "spyglass-ruleset", "grade": "tool"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    E = facts.read_events("m")
    assert facts.input_available(
        "m", E, w, consumer="lint-cdc"
    )  # present, matches recorded
    _write("m", w, "waive-v2-edited")  # edited out-of-band
    assert facts.input_available("m", facts.read_events("m"), w, consumer="lint-cdc")
    (facts.module_root("m") / w).unlink()  # deleted (spec: file missing = cold start)
    assert facts.input_available("m", facts.read_events("m"), w, consumer="lint-cdc")


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


def test_projection_signoff_cell_regresses_on_reopen(tmp_path, monkeypatch):
    # §3.6/§6: reopen of any pin flips the signoff cell back. (The hand-edit half of the
    # §3.6 invariant needs on-disk outputs this empty-outputs fixture cannot carry — it is
    # covered by test_schedule.py::test_projection_signoff_cell_regresses_on_hand_edit.)
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


def test_hand_editing_canonical_result_json_invalidates_proof(tmp_path, monkeypatch):
    # E4 / §5.3: the canonical result.json is in the rule's OWN output binding, so hand-
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
            "objective": "delivery",
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
    # F5: reopen withdraws trust; a bare RE-REAP (re-reading the same run, no re-execution,
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
    # F5 companion: a genuine re-pin (human re-endorses) after reopen DOES restore validity —
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
    # F5 companion: a genuine re-execution (new dispatch AFTER the reopen, then reaped) is
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
            "objective": "delivery",
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


def test_stale_inputs_excludes_self_produced_inout(tmp_path, monkeypatch):
    # lint-cdc's scripts/waiver.tcl is both input and output (in∩out): hand-editing it
    # invalidates the proof (cond-4) but is the stage's OWN product, not an upstream change.
    monkeypatch.chdir(tmp_path)
    _write("m", "Design/rtl-design/mac.v", "v1")
    _write("m", "Design/lint-cdc/scripts/waiver.tcl", "w1")
    recorded = {
        "Design/rtl-design/mac.v": _fp("m", "Design/rtl-design/mac.v"),
        "Design/lint-cdc/scripts/waiver.tcl": _fp(
            "m", "Design/lint-cdc/scripts/waiver.tcl"
        ),
    }
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "lint-cdc",
            "run": 1,
            "workdir": "w",
            "inputs": recorded,
            "params": {},
            "objective": "delivery",
        },
        TS,
    )
    facts.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "lint-cdc",
            "run": 1,
            "verdict": "pass",
            "outputs": {
                "Design/lint-cdc/scripts/waiver.tcl": recorded[
                    "Design/lint-cdc/scripts/waiver.tcl"
                ]
            },
            "proofs": [
                {
                    "name": "lint-cdc",
                    "verdict": "pass",
                    "inputs": recorded,
                    "oracle": {"ref": "spyglass-ruleset", "grade": "tool"},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    evs = facts.read_events("m")
    _write("m", "Design/rtl-design/mac.v", "v2")  # upstream RTL drifts
    _write("m", "Design/lint-cdc/scripts/waiver.tcl", "w2")  # own in∩out product drifts
    result = facts.stale_inputs("m", evs, "lint-cdc")
    assert "Design/rtl-design/mac.v" in result  # upstream change surfaces
    assert "Design/lint-cdc/scripts/waiver.tcl" not in result  # self-produced excluded


def test_stale_inputs_empty_without_prior_outcome(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert facts.stale_inputs("m", [], "rtl-design") == []
