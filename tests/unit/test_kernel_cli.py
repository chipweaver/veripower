"""CLI tests for framework/scripts/kernel.py (subprocess idiom, test_state.py::TestCLI).

Exercises the kernel ENTRY POINT (argparse wiring -> verb handlers -> facts/schedule/
store composition), not the underlying algorithms already covered by
test_facts_*/test_rules/test_route/test_schedule/test_store.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = str(ROOT / "framework" / "scripts" / "kernel.py")
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import kernel  # noqa: E402
import rules  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def _now_iso() -> str:
    """Second-resolution UTC stamp, mirroring the skill finalizers' _now_iso() — so a
    result.json written mid-test passes the reap temporal-integrity check the same way
    a real freshly-finalized envelope does (incl. the same-second floor semantics)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(tmp_path, *args):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )


def _run_json(tmp_path, *args):
    r = _run(tmp_path, *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _write_file(module, rel, content):
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# Minimal pass-valid stage_specific per stage — exactly the per-stage schema's
# status=pass conditional requirements (skills/<stage>/references/result.schema.json),
# so the reap-time schema validation genuinely passes, not vacuously.
_STAGE_SPECIFIC = {
    "specification": {"top_module": "top", "ppa_targets": []},
    "simulation-plan": {},
    "rtl-design": {},
    "lint-cdc": {"violations": []},
    "synthesis": {"ppa_actual": []},
    "timing-analysis": {
        "violations": [],
        "timing": {
            "setup": {"worst_slack_ns": 0.1, "met": True, "worst_path": "p"},
            "hold": {"worst_slack_ns": 0.1, "met": True, "worst_path": "p"},
            "coverage": {
                "unconstrained_max_delay_endpoints": 0,
                "register_pins_no_clock": 0,
            },
        },
    },
    "simulation": {},
    "power-analysis": {
        "saif_artifacts": [],
        "compile_info": {"vcs_version": "test"},
        "failures": [],
        "ppa_actual": [],
        "violations": [],
        "power_by_corner": [],
    },
    "frontend-signoff": {},
}


def _dispatch_write_reap(tmp_path, module, rule, files, *, objective="delivery"):
    """dispatch `rule`, write `files` (workdir-relative path -> content) + a passing
    schema-valid result.json declaring them as artifacts, then reap. Returns the
    reap JSON."""
    d = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        module,
        "--rule",
        rule,
        "--objective",
        objective,
    )
    assert d["ok"] is True, d
    workdir = d["workdir"]
    for rel, content in files.items():
        _write_file(module, f"{workdir}/{rel}", content)
    result = {
        "schema_version": 1,
        "stage": rule,
        "module": module,
        "produced_at": _now_iso(),
        "status": "pass",
        "artifacts": [{"path": p} for p in files],
        "stage_specific": _STAGE_SPECIFIC[rule],
    }
    _write_file(module, f"{workdir}/result.json", json.dumps(result))
    return _run_json(
        tmp_path, "reap", "--module", module, "--rule", rule, "--run", str(d["run"])
    )


# Minimal declared-output set per stage: exactly the files downstream rules' own
# `inputs` selectors reference (per rules.RULES), so the chain stays available/valid
# all the way to frontend-signoff eligibility.
_STAGE_FILES = {
    "specification": {
        "design.md": "design v1",
        "manifest.json": "{}",
        "ppa.json": "{}",
        "constraints/top.sdc": "# sdc",
        "constraints/top.sgdc": "# sgdc",
    },
    "simulation-plan": {
        "verification-plan.md": "plan v1",
        "scaffold-specification.json": "{}",
    },
    "rtl-design": {
        "top.v": "module top; endmodule",
        "filelist.txt": "top.v",
        "README.md": "readme",
    },
    "lint-cdc": {
        "lint-report.txt": "clean",
        "cdc-report.txt": "clean",
    },
    "synthesis": {
        "out/top_syn.v": "module top; endmodule",
        "out/top_syn.sdc": "# sdc",
        "out/top_syn.sdf": "# sdf",
        "reports/qor.rpt": "qor",
    },
    "timing-analysis": {
        "timing-report.txt": "timing ok",
    },
    "simulation": {
        "case-results-summary.md": "all pass",
        "env.sh": "#!/bin/sh",
        "filelist.f": "-f rtl_filelist.f",
        "rtl_filelist.f": "top.v",
        "tb/uvm/dummy.sv": "// tb",
    },
    "power-analysis": {
        "reports_ptpx/run1/power_hier.rpt": "power ok",
    },
}


def _build_full_chain(tmp_path, module):
    """Dispatch+write+reap every stage but frontend-signoff, in FORWARD_PRIORITY
    order, leaving every oracle unpinned (proposed)."""
    _write_file(module, "brainstorm.md", "b1")
    for rule in rules.FORWARD_PRIORITY:
        if rule == "frontend-signoff":
            continue
        outcome = _dispatch_write_reap(tmp_path, module, rule, _STAGE_FILES[rule])
        assert outcome["ok"] is True and outcome["verdict"] == "pass", outcome


def test_cold_start_decide_dispatches_specification(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_file("m", "brainstorm.md", "b1")
    a = _run_json(tmp_path, "decide", "--module", "m")
    assert a["action"] == "DISPATCH"
    assert a["rule"] == "specification"
    assert a["execution"] == "main-thread"


def test_dispatch_then_decide_yields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_file("m", "brainstorm.md", "b1")
    d = _run_json(tmp_path, "dispatch", "--module", "m", "--rule", "specification")
    assert d["ok"] is True
    a = _run_json(tmp_path, "decide", "--module", "m")
    assert a["action"] == "YIELD"
    assert a["in_flight"] == [{"rule": "specification", "run": 1, "has_result": False}]


def test_full_mini_loop_dispatch_result_reap_decide(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_file("m", "brainstorm.md", "b1")
    outcome = _dispatch_write_reap(
        tmp_path, "m", "specification", _STAGE_FILES["specification"]
    )
    assert outcome == {
        "ok": True,
        "rule": "specification",
        "run": 1,
        "verdict": "pass",
    }
    # specification's proof is now valid on disk (promoted); decide advances forward
    # to the next required proof — simulation-plan (index 1 < rtl-design's index 2
    # in FORWARD_PRIORITY; both become available off the same specification outputs).
    a = _run_json(tmp_path, "decide", "--module", "m")
    assert a["action"] == "DISPATCH"
    assert a["rule"] == "simulation-plan"


def test_reap_schema_violation_blocks_and_skips_promote(tmp_path, monkeypatch):
    # result.json parses and carries status=pass, but violates the stage schema
    # (missing the required envelope fields stage/module/produced_at/schema_version
    # and the pass-path stage_specific.top_module/ppa_targets) -> the reap records
    # a blocked outcome with reason schema_violation and promote is NOT called: a
    # malformed-but-status-bearing result.json must never mint a valid proof.
    monkeypatch.chdir(tmp_path)
    _write_file("m", "brainstorm.md", "b1")
    d = _run_json(tmp_path, "dispatch", "--module", "m", "--rule", "specification")
    workdir = d["workdir"]
    _write_file("m", f"{workdir}/design.md", "d1")
    _write_file(
        "m",
        f"{workdir}/result.json",
        json.dumps({"status": "pass", "artifacts": [{"path": "design.md"}]}),
    )
    r = _run_json(
        tmp_path, "reap", "--module", "m", "--rule", "specification", "--run", "1"
    )
    assert r == {"ok": True, "rule": "specification", "run": 1, "verdict": "blocked"}
    outcome = facts.read_events("m")[-1]
    assert outcome["type"] == "outcome" and outcome["verdict"] == "blocked"
    assert outcome["reason"] == "schema_violation"
    assert outcome["outputs"] == {} and outcome["proofs"] == []
    # promote not called: nothing appeared at the canonical stage dir
    canonical = facts.module_root("m") / "Design" / "specification"
    assert not (canonical / "result.json").exists()
    assert not (canonical / "design.md").exists()


def test_signoff_decide_gates_on_proposed_oracle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "gate1")
    a = _run_json(tmp_path, "decide", "--module", "gate1", "--objective", "signoff")
    assert a == {
        "action": "ESCALATE",
        "reason": "signoff blocked: specification oracle is proposed (pin it)",
    }


def test_unknown_rule_argparse_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = _run(tmp_path, "dispatch", "--module", "m", "--rule", "bogus-rule")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr
    assert "Traceback" not in r.stderr


def test_signoff_bypass_blocked_proposed_oracle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "gate3")
    d = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        "gate3",
        "--rule",
        "frontend-signoff",
        "--objective",
        "signoff",
    )
    assert d["ok"] is False
    assert "oracle is proposed (pin it)" in d["error"]


def _latest_grade(module, proof_name="specification"):
    events = facts.read_events(module)
    _, outcome = facts._proof_outcome(events, proof_name)
    proof = next(p for p in outcome["proofs"] if p["name"] == proof_name)
    return proof["oracle"]["grade"]


def test_pin_content_drift_regrades_to_proposed_then_repin_regrades_to_human(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    module = "pintest"
    _write_file(module, "brainstorm.md", "b1")
    files = dict(_STAGE_FILES["specification"])
    files["spec-review.json"] = "review-v1"
    outcome = _dispatch_write_reap(tmp_path, module, "specification", files)
    assert outcome["verdict"] == "pass"
    # First-ever reap: canonical spec-review.json didn't exist pre-reap (UNKNOWN) ->
    # proposed, regardless of any pin. Not asserted; this reap only seeds canonical.

    # pin the CURRENT (canonical, now-promoted) content, then reap again: the grade
    # check now sees a live pin whose recorded fingerprint matches canonical -> human.
    p1 = _run_json(
        tmp_path,
        "pin",
        "--module",
        module,
        "--rule",
        "specification",
        "--provenance",
        "andrew",
        "--reason",
        "review v1",
    )
    assert p1["ok"] is True
    r2 = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r2["ok"] is True
    assert _latest_grade(module) == "human"

    # Drift the oracle's RUN-DIR content (the source promote reads from). The grade
    # check runs BEFORE promote each reap, so it takes two reaps for the drift to be
    # observed: the first propagates the new content onto canonical (still grades
    # human, comparing against the stale pre-promote canonical); the second sees the
    # now-drifted canonical mismatch the old pin -> proposed.
    _write_file(module, "Design/specification/runs/1/spec-review.json", "review-v2")
    r3 = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r3["ok"] is True
    r4 = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r4["ok"] is True
    assert _latest_grade(module) == "proposed"

    # Re-pin at the new (drifted) content -> a fresh live pin matches canonical again.
    p2 = _run_json(
        tmp_path,
        "pin",
        "--module",
        module,
        "--rule",
        "specification",
        "--provenance",
        "andrew",
        "--reason",
        "review v2",
    )
    assert p2["ok"] is True
    r5 = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r5["ok"] is True
    assert _latest_grade(module) == "human"


# ── simulation-triage reap path (Task C7: proof=None -> diagnosis event, not a proof) ──


def _dispatch_triage(tmp_path, module, sim_run):
    d = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--params",
        json.dumps({"sim_run": sim_run}),
    )
    assert d["ok"] is True, d
    return d


def _write_triage_result(module, workdir, *, status, stage_specific):
    result = {
        "schema_version": 1,
        "stage": "simulation-triage",
        "module": module,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": [],
        "stage_specific": stage_specific,
    }
    _write_file(module, f"{workdir}/result.json", json.dumps(result))


def test_triage_complete_reap_emits_outcome_and_diagnosis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "triage1"
    d = _dispatch_triage(tmp_path, module, sim_run=7)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {
                "level": "L2",
                "findings": [
                    {"fault_type": "logic", "anchor": "matvec.v:42", "cases": ["t1"]}
                ],
                "experiment": {
                    "tool": "verilator",
                    "artifacts": ["experiment/harness.sv"],
                    "conclusion": "confirmed",
                },
            },
        },
    )
    r = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d["run"]),
    )
    assert r["ok"] is True
    assert r["verdict"] == "pass"  # non-blocked

    events = facts.read_events(module)
    outcomes = [e for e in events if e["type"] == "outcome"]
    assert len(outcomes) == 1
    assert outcomes[0]["verdict"] == "pass"
    assert outcomes[0]["proofs"] == []  # triage mints no proof

    diagnoses = [e for e in events if e["type"] == "diagnosis"]
    assert len(diagnoses) == 1
    diag = diagnoses[0]
    assert diag["source"] == "triage"
    assert diag["attribution"] == "rtl-design"
    assert diag["fix_owner"] == "rtl-design"
    assert diag["subject"] == {"proof": "simulation", "outcome_run": 7}
    assert diag["confidence"] == "high"
    # D5: fix_locus mapped from advisory.findings[].anchor; evidence includes the triage
    # result.json plus the L2 experiment artifacts (no longer structurally empty).
    assert diag["fix_locus"] == ["matvec.v:42"]
    assert "Verification/simulation-triage/result.json" in diag["evidence"]
    assert "experiment/harness.sv" in diag["evidence"]

    # non-blocked -> promoted to canonical
    canonical = (
        facts.module_root(module) / "Verification" / "simulation-triage" / "result.json"
    )
    assert canonical.exists()


def test_triage_complete_reap_never_yields_fail_verdict(tmp_path, monkeypatch):
    # F3 / spec §2: triage 无独立 fail 态. A schema-legal result.json (the envelope allows
    # status ∈ {pass, fail}; the triage schema does not pin it) that carries status="fail"
    # with analysis_state="complete" must NOT produce an outcome verdict="fail" — a non-proof
    # rule's fail outcome later crashes required_proofs(repair)/step-2's FORWARD_PRIORITY.index.
    monkeypatch.chdir(tmp_path)
    module = "triagefail"
    d = _dispatch_triage(tmp_path, module, sim_run=4)
    _write_triage_result(
        module,
        d["workdir"],
        status="fail",  # schema-legal, but triage has no fail state
        stage_specific={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {
                "level": "L1",
                "findings": [{"fault_type": "logic", "anchor": "a.v:1"}],
            },
        },
    )
    r = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d["run"]),
    )
    assert r["ok"] is True
    assert r["verdict"] != "fail"  # complete triage is never a fail
    outcomes = [e for e in facts.read_events(module) if e["type"] == "outcome"]
    assert outcomes[0]["verdict"] != "fail"
    # the attribution still lands as a diagnosis (complete -> outcome + diagnosis)
    assert any(e["type"] == "diagnosis" for e in facts.read_events(module))


def test_triage_skipped_reap_blocks_no_diagnosis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "triage2"
    d = _dispatch_triage(tmp_path, module, sim_run=3)
    _write_triage_result(
        module,
        d["workdir"],
        status="fail",
        stage_specific={
            "analysis_state": "skipped",
            "skipped_reason": "no fail case to analyze",
        },
    )
    r = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d["run"]),
    )
    assert r["ok"] is True
    assert r["verdict"] == "blocked"

    events = facts.read_events(module)
    outcomes = [e for e in events if e["type"] == "outcome"]
    assert len(outcomes) == 1
    assert outcomes[0]["verdict"] == "blocked"
    assert outcomes[0]["reason"] == "skipped_reason"
    assert outcomes[0]["proofs"] == [] and outcomes[0]["outputs"] == {}
    assert not any(e["type"] == "diagnosis" for e in events)

    # blocked -> never promoted
    canonical = (
        facts.module_root(module) / "Verification" / "simulation-triage" / "result.json"
    )
    assert not canonical.exists()


def test_triage_self_pointing_root_cause_no_fix_owner_no_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "triage3"
    d = _dispatch_triage(tmp_path, module, sim_run=9)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "analysis_state": "complete",
            "root_cause": "simulation",  # self-pointing: attribution recorded, no fix_owner
            "confidence": "high",
            "advisory": {
                "level": "L1",
                "findings": [{"fault_type": "x", "anchor": "a.v:1"}],
            },
        },
    )
    r = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d["run"]),
    )
    assert r["ok"] is True
    assert r["verdict"] == "pass"  # no schema violation, no crash

    events = facts.read_events(module)
    diagnoses = [e for e in events if e["type"] == "diagnosis"]
    assert len(diagnoses) == 1
    diag = diagnoses[0]
    assert diag["attribution"] == "simulation"
    assert "fix_owner" not in diag


# ── reap guard: never-dispatched run (defensive, no TypeError) ─────────────────
#
# NOTE: a re-reap of an ALREADY-outcome'd (rule, run) is deliberately NOT guarded
# against here — ARCHITECTURE.md §4.7/§7.2 documents promote as idempotent so a
# crash mid-promote is repaired by the next reap, and
# test_pin_content_drift_regrades_to_proposed_then_repin_regrades_to_human above
# reaps the same run 4 times in a row (post-pin regrade) and asserts ok:True each
# time. Guarding on "already has an outcome" would break that documented, tested
# behavior, so only the never-dispatched case (no workdir to derive from -> the
# actual TypeError) is guarded.


def test_reap_never_dispatched_ok_false_no_event_appended(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "reapguard1"
    _write_file(module, "brainstorm.md", "b1")
    before = facts.read_events(module)
    r = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r["ok"] is False
    assert facts.read_events(module) == before


# ── B-group regression fixes (kernel-review disposition) ──────────────────


def test_reopen_unknown_pin_ref_rejected(tmp_path, monkeypatch):
    # F6: reopen must not silently no-op on a typo'd pin_ref — a reopen that matches no
    # pinned oracle_ref revokes nothing yet returns ok:true, so the human believes trust
    # was withdrawn when it was not (not a conservative failure). It must error instead.
    monkeypatch.chdir(tmp_path)
    module = "reopenbad"
    facts.append_event(  # a real pin on 'spec-review'
        module,
        {
            "type": "pin",
            "oracle_ref": "spec-review",
            "content_fingerprint": "sha256:x",
            "provenance": "p",
            "reason": "endorse",
        },
        "2026-07-10T00:00:00.000000Z",
    )
    r = _run_json(
        tmp_path,
        "reopen",
        "--module",
        module,
        "--pin-ref",
        "spec-reviewX",
        "--reason",
        "typo",
    )
    assert r["ok"] is False
    assert "spec-reviewX" in r["error"]
    # the good ref still works
    ok = _run_json(
        tmp_path,
        "reopen",
        "--module",
        module,
        "--pin-ref",
        "spec-review",
        "--reason",
        "revoke",
    )
    assert ok["ok"] is True


def test_dispatch_triage_without_sim_run_rejected(tmp_path, monkeypatch):
    # F8a root cause: cmd_dispatch must enforce a rule's declared mandatory params. Without
    # sim_run, the triage reap builds a diagnosis with subject.outcome_run=None -> schema
    # violation AFTER the outcome already landed -> half-reap. Reject the dispatch up front.
    monkeypatch.chdir(tmp_path)
    r = _run_json(tmp_path, "dispatch", "--module", "m", "--rule", "simulation-triage")
    assert r["ok"] is False
    assert "sim_run" in r["error"]


def test_triage_reap_never_leaves_half_reap(tmp_path, monkeypatch):
    # F8a: even if a malformed triage somehow reaches reap, the ledger must never end with
    # an outcome landed but its diagnosis missing (a half-reap). With the dispatch guard the
    # concrete None-sim_run path is closed; assert the guarded dispatch is the only way in.
    monkeypatch.chdir(tmp_path)
    module = "halfreap"
    # dispatch WITH sim_run (the only accepted form) -> complete reap lands both events.
    d = _dispatch_triage(tmp_path, module, sim_run=6)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {
                "level": "L1",
                "findings": [{"fault_type": "x", "anchor": "a.v:1"}],
            },
        },
    )
    r = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d["run"]),
    )
    assert r["ok"] is True
    kinds = [e["type"] for e in facts.read_events(module)]
    assert kinds.count("outcome") == 1 and kinds.count("diagnosis") == 1


def test_re_reap_old_triage_run_uses_its_own_sim_run(tmp_path, monkeypatch):
    # F8b: _derive_triage must key sim_run off the run being reaped, NOT the latest triage
    # dispatch. Re-reaping an older triage run while a newer one exists must label the
    # diagnosis subject with the OLD run's sim_run (mirrors the proof path's per-run lookup).
    monkeypatch.chdir(tmp_path)
    module = "rereap"
    _adv = {"level": "L1", "findings": [{"fault_type": "x", "anchor": "a.v:1"}]}
    d1 = _dispatch_triage(tmp_path, module, sim_run=5)
    _write_triage_result(
        module,
        d1["workdir"],
        status="pass",
        stage_specific={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": _adv,
        },
    )
    _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d1["run"]),
    )
    d2 = _dispatch_triage(
        tmp_path, module, sim_run=9
    )  # a newer triage, different sim_run
    _write_triage_result(
        module,
        d2["workdir"],
        status="pass",
        stage_specific={
            "analysis_state": "complete",
            "root_cause": "simulation-plan",
            "confidence": "high",
            "advisory": _adv,
        },
    )
    _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d2["run"]),
    )
    # RE-REAP the OLD run 1 (its result.json is still on disk)
    _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d1["run"]),
    )
    diags = [e for e in facts.read_events(module) if e["type"] == "diagnosis"]
    # the last diagnosis is from re-reaping run 1 -> must carry run 1's sim_run (5), not 9.
    assert diags[-1]["subject"]["outcome_run"] == 5


def test_dispatch_consumer_in_virgin_module_rejected(tmp_path, monkeypatch):
    # F7: spec §2 — an input whose producer never ran is UNAVAILABLE. A manual dispatch of a
    # consumer (synthesis) in a virgin module (rtl-design/specification never ran) must be
    # rejected; else the run records an empty input table -> a vacuously-valid proof forever.
    monkeypatch.chdir(tmp_path)
    module = "virgin"
    _write_file(module, "brainstorm.md", "b1")
    r = _run_json(tmp_path, "dispatch", "--module", module, "--rule", "synthesis")
    assert r["ok"] is False
    assert "not available" in r["error"]


# ── C-group regression fixes (low-risk corners, kernel-review disposition) ──


def test_dispatch_directive_byte_exact_transfer(tmp_path, monkeypatch):
    # C1 / spec §3.4: the directive is a BYTE-EXACT transfer (triage forward forbids LLM
    # rewrite; the recorded digest must match the source). read_text/write_text applies
    # universal-newline translation (CRLF -> LF), so directive.md and its digest would drift.
    monkeypatch.chdir(tmp_path)
    _write_file("m", "brainstorm.md", "b1")
    src = tmp_path / "directive_src.md"
    src.write_bytes(b"line1\r\nline2\r\n")  # CRLF
    d = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        "m",
        "--rule",
        "specification",
        "--directive",
        str(src),
    )
    dst = facts.module_root("m") / d["workdir"] / "directive.md"
    assert (
        dst.read_bytes() == b"line1\r\nline2\r\n"
    )  # byte-exact, no newline translation
    assert d.get("ok", True)


def test_graded_uses_latest_pin_not_any_live_pin(tmp_path, monkeypatch):
    # C2 / spec §5.4: reap compares the oracle's current content against the LATEST pin
    # record, not ANY live pin. Two live pins (A then B, no reopen between); oracle content
    # reverts to A -> the latest pin (B) does not match -> regrade to proposed, not human.
    monkeypatch.chdir(tmp_path)
    module = "gradepin"
    sr = facts.module_root(module) / "Design" / "specification"
    sr.mkdir(parents=True)
    rev = sr / "spec-review.json"
    rev.write_text("REVIEW-A")
    fpA = facts.fingerprint(rev)
    facts.append_event(
        module,
        {
            "type": "pin",
            "oracle_ref": "spec-review",
            "content_fingerprint": fpA,
            "provenance": "p",
            "reason": "A",
        },
        TS,
    )
    rev.write_text("REVIEW-B")
    fpB = facts.fingerprint(rev)
    facts.append_event(
        module,
        {
            "type": "pin",
            "oracle_ref": "spec-review",
            "content_fingerprint": fpB,
            "provenance": "p",
            "reason": "B",
        },
        TS,
    )
    rev.write_text("REVIEW-A")  # oracle back to A; latest pin (B) no longer matches
    grade = facts.oracle_grade(
        module, facts.read_events(module), rules.RULES["specification"]
    )
    assert grade == "proposed"


def test_proof_evidence_includes_artifacts(tmp_path, monkeypatch):
    # C9 / spec §5.3: proof.evidence = the canonical result.json AND its artifacts[] paths
    # (report-class products are the evidence). Recording only result.json truncates the
    # audit trail.
    monkeypatch.chdir(tmp_path)
    _write_file("m", "brainstorm.md", "b1")
    _dispatch_write_reap(tmp_path, "m", "specification", _STAGE_FILES["specification"])
    _, outcome = facts._proof_outcome(facts.read_events("m"), "specification")
    proof = next(p for p in outcome["proofs"] if p["name"] == "specification")
    ev = proof["evidence"]
    assert "Design/specification/result.json" in ev
    assert any(e.endswith("design.md") for e in ev)  # an artifact beyond result.json


def test_pin_zero_match_selector_rejected(tmp_path, monkeypatch):
    # C10: pinning an oracle whose content selector matches nothing records
    # content_fingerprint="unknown" and returns ok:true — an inert pin that can never grade
    # human. A pin must endorse real content; reject when nothing matches (conservative).
    monkeypatch.chdir(tmp_path)
    r = _run_json(
        tmp_path,
        "pin",
        "--module",
        "m",
        "--rule",
        "specification",
        "--provenance",
        "p",
        "--reason",
        "endorse",
    )
    assert r["ok"] is False
    assert "unknown" in r["error"].lower() or "no content" in r["error"].lower()


def test_triage_high_confidence_without_findings_blocked(tmp_path, monkeypatch):
    # D4/§3.4: a high-confidence complete triage MUST carry non-empty advisory.findings[]
    # each with an anchor (so the auto-routed diagnosis's fix_locus is never empty). A
    # high verdict with no findings violates the schema -> reap derives blocked.
    monkeypatch.chdir(tmp_path)
    module = "d4a"
    d = _dispatch_triage(tmp_path, module, sim_run=1)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
        },
    )  # no advisory.findings
    r = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d["run"]),
    )
    assert r["verdict"] == "blocked"


def test_triage_l2_without_experiment_blocked(tmp_path, monkeypatch):
    # D4/§3.4: an L2 verdict ran a controlled experiment -> advisory.experiment must be
    # present (its artifacts/conclusion are the mapped evidence). L2 without it is blocked.
    monkeypatch.chdir(tmp_path)
    module = "d4b"
    d = _dispatch_triage(tmp_path, module, sim_run=1)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {
                "level": "L2",
                "findings": [{"fault_type": "x", "anchor": "a.v:1"}],
            },
        },
    )
    r = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "simulation-triage",
        "--run",
        str(d["run"]),
    )
    assert r["verdict"] == "blocked"


# ── reap temporal-integrity check (room-birth hygiene, ARCHITECTURE §4.7/§7.2) ──
#
# The kernel's only trust input from a workdir is result.json; a produced_at predating
# this run's own dispatch means the envelope was carried in (e.g. a canonical result.json
# copied into the room), not authored by this run's executor. Without this check the
# whitewash is fully automatic: decide step 0 auto-REAPs any in-flight run whose workdir
# holds a result.json, so an interrupted seeded run would land a stale pass with a fresh
# inputs table.


def test_reap_stale_produced_at_blocked_no_promote(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "stale1"
    _write_file(module, "brainstorm.md", "b1")
    d = _run_json(tmp_path, "dispatch", "--module", module, "--rule", "specification")
    workdir = d["workdir"]
    for rel, content in _STAGE_FILES["specification"].items():
        _write_file(module, f"{workdir}/{rel}", content)
    result = {
        "schema_version": 1,
        "stage": "specification",
        "module": module,
        "produced_at": "2026-07-10T00:00:00Z",  # predates the just-made dispatch
        "status": "pass",
        "artifacts": [{"path": p} for p in _STAGE_FILES["specification"]],
        "stage_specific": _STAGE_SPECIFIC["specification"],
    }
    _write_file(module, f"{workdir}/result.json", json.dumps(result))
    r = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r == {"ok": True, "rule": "specification", "run": 1, "verdict": "blocked"}
    outcome = facts.read_events(module)[-1]
    assert outcome["reason"] == "stale_result"
    assert outcome["outputs"] == {} and outcome["proofs"] == []
    canonical = facts.module_root(module) / "Design" / "specification"
    assert not (canonical / "result.json").exists()  # blocked never promotes


def test_reap_same_second_produced_at_not_misjudged(tmp_path, monkeypatch):
    # Skill finalizers stamp second-resolution UTC while the kernel dispatch ts carries
    # microseconds: a sub-second run's produced_at can equal the dispatch second exactly.
    # The check floors the dispatch ts, so the boundary case must reap pass, not stale.
    monkeypatch.chdir(tmp_path)
    module = "boundary1"
    _write_file(module, "brainstorm.md", "b1")
    d = _run_json(tmp_path, "dispatch", "--module", module, "--rule", "specification")
    dispatch_ts = facts.read_events(module)[-1]["ts"]  # %Y-%m-%dT%H:%M:%S.%fZ
    workdir = d["workdir"]
    for rel, content in _STAGE_FILES["specification"].items():
        _write_file(module, f"{workdir}/{rel}", content)
    result = {
        "schema_version": 1,
        "stage": "specification",
        "module": module,
        "produced_at": dispatch_ts[:19] + "Z",  # dispatch second, microseconds dropped
        "status": "pass",
        "artifacts": [{"path": p} for p in _STAGE_FILES["specification"]],
        "stage_specific": _STAGE_SPECIFIC["specification"],
    }
    _write_file(module, f"{workdir}/result.json", json.dumps(result))
    r = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r["verdict"] == "pass", r


def test_reap_unparseable_produced_at_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "stale2"
    _write_file(module, "brainstorm.md", "b1")
    d = _run_json(tmp_path, "dispatch", "--module", module, "--rule", "specification")
    workdir = d["workdir"]
    for rel, content in _STAGE_FILES["specification"].items():
        _write_file(module, f"{workdir}/{rel}", content)
    result = {
        "schema_version": 1,
        "stage": "specification",
        "module": module,
        "produced_at": "yesterday-ish",  # schema-legal string, not a timestamp
        "status": "pass",
        "artifacts": [{"path": p} for p in _STAGE_FILES["specification"]],
        "stage_specific": _STAGE_SPECIFIC["specification"],
    }
    _write_file(module, f"{workdir}/result.json", json.dumps(result))
    r = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r["verdict"] == "blocked"
    assert facts.read_events(module)[-1]["reason"] == "produced_at_unparseable"


def test_stale_result_reason_boundaries():
    # Direct boundary semantics of the helper: same-second passes (floored dispatch),
    # earlier second is stale, naive timestamps are taken as UTC, garbage is unparseable.
    f = kernel._stale_result_reason
    assert f("2026-07-10T00:00:00Z", "2026-07-10T00:00:00.900000Z") is None
    assert f("2026-07-10T00:00:00Z", "2026-07-10T00:00:01.000000Z") == "stale_result"
    assert f("2026-07-10T00:00:01Z", "2026-07-10T00:00:00.900000Z") is None
    assert f("2026-07-10T00:00:00", "2026-07-10T00:00:00.900000Z") is None  # naive=UTC
    assert (
        f("yesterday-ish", "2026-07-10T00:00:00.000000Z") == "produced_at_unparseable"
    )
    assert f(None, "2026-07-10T00:00:00.000000Z") == "produced_at_unparseable"


def test_bare_import_single_module_identity():
    # Cross-module SSoT identity (CONTRIBUTING "Modifying the kernel"): kernel/schedule/facts
    # import the shared leaf modules the bare way off the same sys.path, so each resolves to
    # ONE object. The package-path form (`framework.scripts.rules`) would mint a second module,
    # splitting rules.RULES / facts freshness. Guards the dup-module bug class (replaces the
    # retired test_topology.py identity check).
    import schedule  # noqa: E402

    assert kernel.rules is schedule.rules is facts.rules
    assert kernel.schedule is schedule
    assert kernel.facts is schedule.facts is facts
