"""CLI tests for framework/scripts/kernel.py (subprocess idiom, test_state.py::TestCLI).

Exercises the kernel ENTRY POINT (argparse wiring -> verb handlers -> facts/schedule/
store composition), not the underlying algorithms already covered by
test_facts_*/test_rules/test_schedule.
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
                "output_bits": 4,
                "output_bits_timed": 4,
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
        "power_by_scenario": [],
    },
}


def _dispatch_write_reap(tmp_path, module, rule, files):
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
    )
    assert d["ok"] is True, d
    workdir = d["workdir"]
    for rel, content in files.items():
        _write_file(module, f"{workdir}/{rel}", content)
    result = {
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
# all the way to a clear signoff gate.
_STAGE_FILES = {
    "specification": {
        "design.md": "design v1",
        "manifest.json": "{}",
        "ppa.json": "{}",
        "clocks.json": "[]",
        "features.json": "[]",
        "timing-scenarios.json": "[]",
        "check-hints/c.json": "[]",
        "top-io.json": "[]",
        "interconnects.json": "[]",
        "constraints/top.sdc": "# sdc",
        "constraints/top.sgdc": "# sgdc",
    },
    "simulation-plan": {
        "verification-plan.md": "plan v1",
        "tb-scaffold.json": "{}",
        "sequences.json": "[]",
        "power-scenarios.json": "[]",
    },
    "rtl-design": {
        "top.v": "module top; endmodule",
        "rtl-files.json": '{"c": {"files": ["top.v"]}}',
        "constraint-annotations.json": "{}",
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


# Content each proposed-oracle rule's oracle_selector points at. Kept out of _STAGE_FILES
# (which other tests share) and folded in only by _build_full_chain: without it a pin has
# nothing to endorse — oracle_content_fp reads UNKNOWN and cmd_pin refuses. The oracles stay
# `proposed` until someone actually pins them; writing the record is not endorsing it.
_ORACLE_CONTENT = {
    "specification": {"spec-review/core.md": "spec review v1"},
    "simulation-plan": {"plan-review/review.md": "plan review v1"},
    "rtl-design": {"semantic-review/leaf.md": "semantic review v1"},
    "simulation": {"tb/uvm/refmodel/ref.sv": "// refmodel v1"},
}


def _build_full_chain(tmp_path, module):
    """Dispatch+write+reap every stage, in FORWARD_PRIORITY order, leaving every
    oracle unpinned (proposed) but pinnable."""
    _write_file(module, "brainstorm.md", "b1")
    for rule in rules.FORWARD_PRIORITY:
        files = {**_STAGE_FILES[rule], **_ORACLE_CONTENT.get(rule, {})}
        outcome = _dispatch_write_reap(tmp_path, module, rule, files)
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
    assert a["in_flight"] == [{"rule": "specification", "run": 1}]


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
    # (missing the required envelope fields stage/module/produced_at
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
    a = _run_json(tmp_path, "decide", "--module", "gate1", "--closing")
    assert a == {
        "action": "ESCALATE",
        "reason": "signoff blocked: specification oracle is proposed (pin it)",
    }


def _pin_every_proposed_oracle(tmp_path, module):
    for rule in rules.FORWARD_PRIORITY:
        if rules.RULES[rule].oracle[1] == "proposed":
            p = _run_json(
                tmp_path,
                "pin",
                "--module",
                module,
                "--rule",
                rule,
                "--provenance",
                "reviewer",
                "--reason",
                "endorsed",
            )
            assert p["ok"] is True, p


def test_signoff_close_end_to_end(tmp_path, monkeypatch):
    # The whole trust boundary in one pass, through the real CLI: a delivered chain is NOT
    # signed off; decide refuses while any oracle is merely proposed; pinning each one lifts
    # the gate to DONE ("go stamp"); the verb lands the human act; only then does status say
    # signed_off. Each step is the reason the next one is allowed.
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "close")
    assert _run_json(tmp_path, "status", "--module", "close")["signed_off"] is False
    _pin_every_proposed_oracle(tmp_path, "close")
    a = _run_json(tmp_path, "decide", "--module", "close", "--closing")
    assert a["action"] == "DONE"  # gate clear — but nothing is signed off yet
    assert _run_json(tmp_path, "status", "--module", "close")["signed_off"] is False
    s = _run_json(
        tmp_path,
        "signoff",
        "--module",
        "close",
        "--provenance",
        "owner",
        "--reason",
        "tapeout rc1",
    )
    assert s["ok"] is True
    assert _run_json(tmp_path, "status", "--module", "close")["signed_off"] is True
    # and the verb hands back WHAT was signed, not just that it worked: every proof, its
    # oracle's live grade, and for a human grade the fingerprint the pin named.
    basis = {b["proof"]: b for b in s["basis"]}
    assert set(basis) == set(a["basis"][i]["proof"] for i in range(len(a["basis"])))
    for b in basis.values():
        assert b["oracle"]["grade"] in ("tool", "human")
        if b["oracle"]["grade"] == "human":
            assert b["oracle"]["pinned_fingerprint"].startswith("sha256:")
        assert b["inputs"] == sorted(b["inputs"])


def test_reopen_drops_a_landed_signoff(tmp_path, monkeypatch):
    # §3.6: a signoff is only as good as the proofs beneath it. The signoff event is
    # permanent and there is no unsign verb — reopening any pin invalidates that proof
    # (cond 3), which drops the predicate's second conjunct. No ceremony required.
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "revoke")
    _pin_every_proposed_oracle(tmp_path, "revoke")
    _run_json(
        tmp_path,
        "signoff",
        "--module",
        "revoke",
        "--provenance",
        "owner",
        "--reason",
        "tapeout rc1",
    )
    assert _run_json(tmp_path, "status", "--module", "revoke")["signed_off"] is True
    r = _run_json(
        tmp_path,
        "reopen",
        "--module",
        "revoke",
        "--pin-ref",
        "spec-review",
        "--reason",
        "found a hole",
    )
    assert r["ok"] is True
    assert _run_json(tmp_path, "status", "--module", "revoke")["signed_off"] is False


def test_unknown_rule_argparse_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = _run(tmp_path, "dispatch", "--module", "m", "--rule", "bogus-rule")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr
    assert "Traceback" not in r.stderr


def test_signoff_bypass_blocked_proposed_oracle(tmp_path, monkeypatch):
    # §6: the gate must not be bypassable. The verb is now its ONLY surface, so calling
    # `signoff` directly — never going near `decide` — must still hit the gate and refuse.
    # No signoff event may land behind a refusal.
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "gate3")
    d = _run_json(
        tmp_path,
        "signoff",
        "--module",
        "gate3",
        "--provenance",
        "someone",
        "--reason",
        "ship it",
    )
    assert d["ok"] is False
    assert "oracle is proposed (pin it)" in d["error"]
    assert not any(e["type"] == "signoff" for e in facts.read_events("gate3"))


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
    files["spec-review/core.md"] = "review-v1"
    outcome = _dispatch_write_reap(tmp_path, module, "specification", files)
    assert outcome["verdict"] == "pass"
    # First-ever reap: canonical spec-review/core.md didn't exist pre-reap (UNKNOWN) ->
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
    _write_file(module, "Design/specification/runs/1/spec-review/core.md", "review-v2")
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
    # Triage only ever fires as a disposition on a simulation failure, so its module
    # directory always exists by then. Seed it: the CLI refuses a module with no directory,
    # since module paths resolve against cwd and an absent one is a wrong-cwd mistake.
    _write_file(module, "brainstorm.md", "b1")
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
                "findings": [{"anchor": "matvec.v:42", "cases": ["t1"]}],
                "experiment": {
                    "tool": "verilator",
                    "artifacts": ["experiment/harness.sv"],
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
    # result.json plus the experiment artifacts (no longer structurally empty). Every
    # entry is anchored on THIS triage run's directory, which keeps the list module-relative
    # throughout and immutable: canonical result.json is overwritten by the next triage,
    # runs/<N>/ is not, and the artifacts are workdir-relative at the source.
    assert diag["fix_locus"] == ["matvec.v:42"]
    run_dir = f"Verification/simulation-triage/runs/{d['run']}"
    assert diag["evidence"] == [
        f"{run_dir}/result.json",
        f"{run_dir}/experiment/harness.sv",
    ]

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
                "findings": [{"anchor": "a.v:1"}],
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
                "findings": [{"anchor": "a.v:1"}],
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
    _write_file("m", "brainstorm.md", "b1")
    r = _run_json(tmp_path, "dispatch", "--module", "m", "--rule", "simulation-triage")
    assert r["ok"] is False
    assert "sim_run" in r["error"]


def test_unknown_module_directory_is_a_hard_error(tmp_path, monkeypatch):
    """Module paths resolve against cwd, so an absent module directory is a wrong-cwd
    mistake, never a starting state — brainstorm.md must already exist for anything to be
    dispatchable. Both verbs used to answer as if the module were merely empty: `status`
    invented an all-`missing` projection at exit 0, and `decide` returned the same
    "no eligible rule" ESCALATE a genuinely deadlocked module returns."""
    monkeypatch.chdir(tmp_path)
    for verb in ("status", "decide"):
        r = _run(tmp_path, verb, "--module", "nosuch")
        assert r.returncode != 0, r.stdout
        assert "no module directory" in r.stderr
        assert str(tmp_path / "asic" / "nosuch") in r.stderr


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
                "findings": [{"anchor": "a.v:1"}],
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
    _adv = {"findings": [{"anchor": "a.v:1"}]}
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


def test_graded_uses_latest_pin_not_any_live_pin(tmp_path, monkeypatch):
    # C2 / spec §5.4: reap compares the oracle's current content against the LATEST pin
    # record, not ANY live pin. Two live pins (A then B, no reopen between); oracle content
    # reverts to A -> the latest pin (B) does not match -> regrade to proposed, not human.
    monkeypatch.chdir(tmp_path)
    module = "gradepin"
    sr = facts.module_root(module) / "Design" / "specification"
    sr.mkdir(parents=True)
    (sr / "spec-review").mkdir()
    rev = sr / "spec-review" / "core.md"
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


def test_outputs_name_the_artifacts_that_are_the_evidence(tmp_path, monkeypatch):
    # C9 / spec §5.3: the report-class products ARE the evidence, so the outcome must name
    # the canonical result.json AND every artifacts[] path — recording only result.json
    # truncates the audit trail. `outputs` carries them with their fingerprints, which is
    # why the proof no longer repeats the bare paths beside it.
    monkeypatch.chdir(tmp_path)
    _write_file("m", "brainstorm.md", "b1")
    _dispatch_write_reap(tmp_path, "m", "specification", _STAGE_FILES["specification"])
    _, outcome = facts._proof_outcome(facts.read_events("m"), "specification")
    outs = outcome["outputs"]
    assert "Design/specification/result.json" in outs
    assert any(o.endswith("design.md") for o in outs)  # an artifact beyond result.json
    assert all(v.startswith(("sha256:", "merkle:")) for v in outs.values())
    proof = next(p for p in outcome["proofs"] if p["name"] == "specification")
    assert "evidence" not in proof


def test_pin_zero_match_selector_rejected(tmp_path, monkeypatch):
    # C10: pinning an oracle whose content selector matches nothing records
    # content_fingerprint="unknown" and returns ok:true — an inert pin that can never grade
    # human. A pin must endorse real content; reject when nothing matches (conservative).
    monkeypatch.chdir(tmp_path)
    _write_file("m", "brainstorm.md", "b1")
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


def test_dispatch_writes_dispatch_json(tmp_path, monkeypatch):
    # cold specification dispatch → workdir has dispatch.json with the brainstorm location
    monkeypatch.chdir(tmp_path)
    (tmp_path / "asic" / "m").mkdir(parents=True)
    (tmp_path / "asic" / "m" / "brainstorm.md").write_text("bs")
    r = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        "m",
        "--rule",
        "specification",
    )
    wd = tmp_path / "asic" / "m" / r["workdir"]
    table = json.loads((wd / "dispatch.json").read_text())["inputs"]
    assert table["brainstorm"] == str((tmp_path / "asic" / "m").resolve())


def test_dispatch_carries_author_previous_round(tmp_path, monkeypatch):
    # seed a canonical specification product, then re-dispatch → carried into new workdir
    monkeypatch.chdir(tmp_path)
    canon = tmp_path / "asic" / "m" / "Design" / "specification"
    canon.mkdir(parents=True)
    (canon / "design.md").write_text("prev")
    (tmp_path / "asic" / "m" / "brainstorm.md").write_text("bs")
    r = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        "m",
        "--rule",
        "specification",
    )
    wd = tmp_path / "asic" / "m" / r["workdir"]
    assert (wd / "design.md").read_text() == "prev"


def test_dispatch_injects_no_upstream_byte_copy(tmp_path, monkeypatch):
    # §10 #2 (half a): a transformer dispatch writes ONLY dispatch.json — the upstream RTL is
    # injected as a location, never copied into the workdir. (Half b — editing canonical
    # invalidates the proof — is covered by test_facts_freshness input-change tests.)
    monkeypatch.chdir(tmp_path)
    # seed enough upstream so synthesis is dispatchable: specification then rtl-design,
    # each taken through a real dispatch+result+reap (mirrors _dispatch_write_reap /
    # _build_full_chain) so their outcomes are recorded and rule_available sees them.
    _write_file("m", "brainstorm.md", "bs")
    _dispatch_write_reap(tmp_path, "m", "specification", _STAGE_FILES["specification"])
    _dispatch_write_reap(tmp_path, "m", "rtl-design", _STAGE_FILES["rtl-design"])
    r = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        "m",
        "--rule",
        "synthesis",
    )
    wd = tmp_path / "asic" / "m" / r["workdir"]
    assert (wd / "dispatch.json").is_file()
    assert not (wd / "top.v").exists()  # upstream RTL injected, not copied


def test_dispatch_proof_inputs_excludes_self_carry(tmp_path, monkeypatch):
    # §10 #4: an author's carried self-products are NOT in Rule.inputs, so the dispatch event's
    # recorded input table (proof.inputs source) never contains them — dropping/editing a
    # carried product cannot stale the author's fresh proof.
    monkeypatch.chdir(tmp_path)
    canon = tmp_path / "asic" / "m" / "Design" / "specification"
    canon.mkdir(parents=True)
    (canon / "design.md").write_text(
        "prev"
    )  # a self-PRODUCT (output), carried, not an input
    (tmp_path / "asic" / "m" / "brainstorm.md").write_text("bs")
    _run_json(
        tmp_path,
        "dispatch",
        "--module",
        "m",
        "--rule",
        "specification",
    )
    events = [
        json.loads(ln)
        for ln in (tmp_path / "asic" / "m" / "events.jsonl").read_text().splitlines()
    ]
    disp = [e for e in events if e["type"] == "dispatch"][-1]
    assert set(disp["inputs"]) == {"brainstorm.md"}  # design.md (self-product) absent


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
