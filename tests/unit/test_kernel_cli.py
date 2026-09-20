"""CLI tests for framework/scripts/kernel.py (subprocess idiom, test_state.py::TestCLI).

Exercises the kernel ENTRY POINT (argparse wiring -> verb handlers -> facts/schedule/
store composition), not the underlying algorithms already covered by
test_facts_*/test_rules/test_schedule.
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = str(ROOT / "framework" / "scripts" / "kernel.py")
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import kernel  # noqa: E402
import rules  # noqa: E402
import store  # noqa: E402

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
    """The kernel leaves the intent tree unwritable, and revising it is `chmod u+w` then edit,
    so take the write bit back on every existing ancestor first."""
    root = store.module_root(module)
    p = root / rel
    intent = root / "intent"
    # The kernel leaves the intent tree unwritable; revising it is `chmod -R u+w intent`
    # then edit, which is what a test that changes the engineer's document is doing.
    if intent.exists() and str(p).startswith(str(intent)):
        for q in (intent, *intent.rglob("*")):
            if not q.is_symlink():
                q.chmod(q.stat().st_mode | 0o200)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# Minimal pass-valid stage_specific per stage — exactly the per-stage schema's
# status=pass conditional requirements (skills/<stage>/references/result.schema.json),
# so the reap-time schema validation genuinely passes, not vacuously.
_STAGE_SPECIFIC = {
    "specification": {"top_module": "top"},
    "simulation-plan": {},
    "rtl-design": {},
    "lint-cdc": {"violations": [], "requirements": []},
    # Non-empty on purpose: this verdict is what test_signoff_close_end_to_end follows
    # from result.json through reap into the basis a human is handed.
    "synthesis": {
        "requirements": [
            {
                "id": "R-1",
                "met": True,
                "actual": 0.0,
                "measured": "timing_setup.rpt minimum setup slack",
            }
        ]
    },
    "timing-analysis": {
        "violations": [],
        "requirements": [],
        "timing": {
            "setup": {"worst_slack_ns": 0.1, "met": True, "worst_path": "p"},
            "hold": {"worst_slack_ns": 0.1, "met": True, "worst_path": "p"},
        },
    },
    "simulation": {},
    "power-analysis": {
        "saif_artifacts": [],
        "compile_info": {"vcs_version": "test"},
        "failures": [],
        "requirements": [],
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
        "children/c.md": "child v1",
        "manifest.json": "{}",
        "requirements.json": "[]",
        "clocks.json": "[]",
        "check-hints.json": "[]",
        "top-io.json": "[]",
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
        "src/top.v": "module top; endmodule",
        "rtl-files.json": '{"c": {"files": ["src/top.v"]}}',
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
        "scripts/run_vcs_regression.sh": "#!/bin/sh\n",
        "tb/uvm/dummy.sv": "// tb",
        "tests/testlist.json": "[]",
    },
    "power-analysis": {
        "reports_ptpx/run1/power_hier.rpt": "power ok",
    },
}


# Include delivered reviews and the reference model in the full-chain fixture.
_REVIEW_CONTENT = {
    "specification": {"spec-review/core.md": "spec review v1"},
    "simulation-plan": {"plan-review/review.md": "plan review v1"},
    "rtl-design": {"semantic-review/leaf.md": "semantic review v1"},
    "simulation": {"tb/uvm/refmodel/ref.sv": "// refmodel v1"},
}


def _build_full_chain(tmp_path, module):
    """Dispatch, write and reap all stages without recording acceptance."""
    _write_file(module, "intent/brainstorm.md", "b1")
    for rule in rules.FORWARD_PRIORITY:
        files = {**_STAGE_FILES[rule], **_REVIEW_CONTENT.get(rule, {})}
        outcome = _dispatch_write_reap(tmp_path, module, rule, files)
        assert outcome["ok"] is True and outcome["verdict"] == "pass", outcome


def test_cold_start_decide_dispatches_specification(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_file("m", "intent/brainstorm.md", "b1")
    a = _run_json(tmp_path, "decide", "--module", "m")
    assert a["action"] == "DISPATCH"
    assert a["rule"] == "specification"
    assert a["execution"] == "main-thread"


def test_dispatch_then_decide_yields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_file("m", "intent/brainstorm.md", "b1")
    d = _run_json(tmp_path, "dispatch", "--module", "m", "--rule", "specification")
    assert d["ok"] is True
    a = _run_json(tmp_path, "decide", "--module", "m")
    assert a["action"] == "YIELD"
    assert a["in_flight"] == [{"rule": "specification", "run": 1}]


def test_full_mini_loop_dispatch_result_reap_decide(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_file("m", "intent/brainstorm.md", "b1")
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
    # and the pass-path stage_specific.top_module) -> the reap records
    # a blocked outcome with the validation reason and promote is NOT called: a
    # malformed-but-status-bearing result.json must never mint a valid proof.
    monkeypatch.chdir(tmp_path)
    _write_file("m", "intent/brainstorm.md", "b1")
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
    assert r["ok"] and r["verdict"] == "blocked"
    assert "stage" in r["reason"] and "required" in r["reason"]
    outcome = store.read_events("m")[-1]
    assert outcome["type"] == "outcome" and outcome["verdict"] == "blocked"
    assert outcome["reason"] == r["reason"]
    assert outcome["outputs"] == {} and outcome["proofs"] == []
    # promote not called: nothing appeared at the canonical stage dir
    canonical = store.module_root("m") / "Design" / "specification"
    assert not (canonical / "result.json").exists()
    assert not (canonical / "design.md").exists()


def test_signoff_close_end_to_end(tmp_path, monkeypatch):
    # Readiness is distinct from the explicit acceptance recorded by signoff.
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "close")
    assert _run_json(tmp_path, "status", "--module", "close")["signed_off"] is False
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
    # The response identifies the conclusions and evidence accepted.
    basis = {b["proof"]: b for b in s["basis"]}
    assert set(basis) == set(a["basis"][i]["proof"] for i in range(len(a["basis"])))
    for b in basis.values():
        assert b["inputs"] == sorted(b["inputs"])
    # and the bound judgments themselves, carried up from the stage's own result.json:
    # for the four tool stages this is the only place one reaches a human, and a verdict
    # without the measurement behind it names a dimension rather than a number.
    assert (
        basis["synthesis"]["requirements"]
        == _STAGE_SPECIFIC["synthesis"]["requirements"]
    )


def test_signoff_stays_bound_to_the_accepted_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "accepted-evidence"
    _build_full_chain(tmp_path, module)

    def status():
        return kernel.cmd_status(module)["signed_off"]

    def sign():
        assert kernel.cmd_signoff(
            module, "delegated reviewer", "accept current evidence"
        )["ok"]

    sign()
    assert status()
    # A normal repeat reap preserves unchanged evidence.
    assert kernel.cmd_reap(module, "specification", 1)["ok"]
    assert status()
    extra = store.module_root(module) / "Verification/power-analysis/extra.txt"
    extra.write_text("unrecorded")
    assert not status()
    extra.unlink()
    assert status()

    events = store.read_events(module)
    wd = store.module_root(module) / facts.run_workdir(events, "power-analysis", 1)
    (wd / "reports_ptpx/run1/power_hier.rpt").write_text("changed measurement")
    assert kernel.cmd_reap(module, "power-analysis", 1)["ok"]
    assert facts.signoff_gate(module, store.read_events(module)) is None
    assert not status()  # Same run, different evidence requires new acceptance.
    sign()
    assert status()

    files = dict(_STAGE_FILES["power-analysis"])
    files["reports_ptpx/run1/power_hier.rpt"] = "new run measurement"
    assert _dispatch_write_reap(tmp_path, module, "power-analysis", files)["ok"]
    assert facts.signoff_gate(module, store.read_events(module)) is None
    assert not status()
    sign()
    assert status()


def test_unknown_rule_argparse_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = _run(tmp_path, "dispatch", "--module", "m", "--rule", "bogus-rule")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr
    assert "Traceback" not in r.stderr


# ── simulation-triage reap path (proof=None -> diagnosis event, not a proof) ───────────


def _dispatch_triage(tmp_path, module, sim_run):
    # Triage only ever fires as a disposition on a simulation failure, so its module
    # directory always exists by then. Seed it: the CLI refuses a module with no directory,
    # since module paths resolve against cwd and an absent one is a wrong-cwd mistake.
    _write_file(module, "intent/brainstorm.md", "b1")
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
            "findings": [
                {
                    "anchor": "matvec.v:42",
                    "cases": ["t1"],
                    "root_cause": "rtl-design",
                    "reason": "the tap is read one cycle late",
                }
            ],
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

    events = store.read_events(module)
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
    # Nothing beyond the naming is copied onto the record: where the fix goes is in the
    # analysis (findings[].anchor), and what it rests on is addressable from the
    # `subject` it already carries — the dispatch derives both (_diagnosis_sources).
    assert "fix_locus" not in diag and "evidence" not in diag

    # non-blocked -> promoted to canonical
    canonical = (
        store.module_root(module) / "Verification" / "simulation-triage" / "result.json"
    )
    assert canonical.exists()


def test_triage_splits_one_analysis_into_one_diagnosis_per_root_cause(
    tmp_path, monkeypatch
):
    """A regression fails for as many reasons as it fails for. A real analysis named
    `simulation-plan` while its loci reached into RTL and the testbench, and the record could
    hold only one owner, so a human had to notice and dispatch the second by hand. Per-finding
    `root_cause` splits it: one diagnosis per distinct owner, each carrying its own anchors
    and all binding to the run that was analysed."""
    monkeypatch.chdir(tmp_path)
    module = "triage-split"
    d = _dispatch_triage(tmp_path, module, sim_run=4)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "findings": [
                {
                    "anchor": "verification-plan.md:88",
                    "cases": ["t1"],
                    "root_cause": "simulation-plan",
                    "reason": "no testpoint drives the back-to-back case",
                },
                {
                    "anchor": "core_muldiv.v:129",
                    "cases": ["t2"],
                    "root_cause": "rtl-design",
                    "reason": "the divider stalls one cycle short",
                },
                {
                    "anchor": "sequences.json:12",
                    "cases": ["t3"],
                    "root_cause": "simulation-plan",
                    "reason": "the sequence never raises backpressure",
                },
            ],
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
    diagnoses = [e for e in store.read_events(module) if e["type"] == "diagnosis"]
    by_owner = {e["fix_owner"]: e for e in diagnoses}
    assert set(by_owner) == {"simulation-plan", "rtl-design"}
    # both rest on the same analysis, and both bind to the run that was analysed
    assert len({e["id"] for e in diagnoses}) == 2
    for e in diagnoses:
        assert e["subject"] == {"proof": "simulation", "outcome_run": 4}


def test_triage_complete_reap_never_yields_fail_verdict(tmp_path, monkeypatch):
    # A completed diagnosis records analysis completion, not a verification failure.
    monkeypatch.chdir(tmp_path)
    module = "triagefail"
    d = _dispatch_triage(tmp_path, module, sim_run=4)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "findings": [
                {"anchor": "a.v:1", "root_cause": "rtl-design", "reason": "why"}
            ],
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
    outcomes = [e for e in store.read_events(module) if e["type"] == "outcome"]
    assert outcomes[0]["verdict"] != "fail"
    # the attribution still lands as a diagnosis (complete -> outcome + diagnosis)
    assert any(e["type"] == "diagnosis" for e in store.read_events(module))


def test_unresolved_triage_is_delivered_and_uses_existing_decision_path(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    module = "unresolved"
    _build_full_chain(tmp_path, module)
    d = kernel.cmd_dispatch(module, "simulation", None)
    sim_cli = ROOT / "skills/simulation/scripts/sim/__main__.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(sim_cli),
            "finalize",
            "--workdir",
            d["workdir"],
            "--phase",
            "fail",
            "--fail-reason",
            "Mismatch; cause needs investigation",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert kernel.cmd_reap(module, "simulation", d["run"])["verdict"] == "fail"
    action = kernel.schedule.decide(module)
    assert action["rule"] == "simulation-triage"
    td = kernel.cmd_dispatch(
        module, action["rule"], None, action["params"], action["caused_by"]
    )
    tri_cli = ROOT / "skills/simulation-triage/scripts/simtriage/__main__.py"
    reason = (
        "The retained run lacks the observation needed to distinguish the two causes"
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(tri_cli),
            "finalize",
            "--workdir",
            td["workdir"],
            "--json-stdin",
        ],
        input=json.dumps({"findings": [], "reason": reason}),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert kernel.cmd_reap(module, "simulation-triage", td["run"])["verdict"] == "pass"
    events = store.read_events(module)
    diagnosis = events[-1]
    # Repeated collection preserves one unresolved decision.
    assert kernel.cmd_reap(module, "simulation-triage", td["run"])["verdict"] == "pass"
    events = store.read_events(module)
    assert [e for e in events if e["type"] == "diagnosis"] == [diagnosis]
    assert diagnosis["type"] == "diagnosis" and diagnosis["reason"] == reason
    assert "attribution" not in diagnosis and "fix_owner" not in diagnosis
    assert (
        store.module_root(module) / "Verification/simulation-triage/result.json"
    ).exists()
    for _ in range(2):
        action = kernel.schedule.decide(module)
        assert action["action"] == "ESCALATE"
        assert action["candidates"] == [
            {"diagnosis": diagnosis["id"], "reason": reason}
        ]
    assert store.read_events(module) == events
    assert kernel.cmd_diagnose(
        module,
        "resolved",
        "simulation",
        d["run"],
        None,
        "simulation",
        "delegated fixture",
        "New observation identifies the checker defect",
        diagnosis["id"],
    )["ok"]
    action = kernel.schedule.decide(module)
    assert action["action"] == "DISPATCH" and action["rule"] == "simulation"
    assert action["caused_by"] == [["simulation", d["run"]]]
    assert action["diagnosis_refs"] == ["resolved"]
    # Recollecting the same analysis must not undo the resolved attribution.
    assert kernel.cmd_reap(module, "simulation-triage", td["run"])["verdict"] == "pass"
    action = kernel.schedule.decide(module)
    assert action["action"] == "DISPATCH" and action["diagnosis_refs"] == ["resolved"]


def test_triage_local_root_cause_names_local_repair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "triage3"
    d = _dispatch_triage(tmp_path, module, sim_run=9)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "findings": [
                {"anchor": "a.v:1", "root_cause": "simulation", "reason": "why"}
            ],
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

    events = store.read_events(module)
    diagnoses = [e for e in events if e["type"] == "diagnosis"]
    assert len(diagnoses) == 1
    diag = diagnoses[0]
    assert diag["attribution"] == "simulation"
    assert diag["fix_owner"] == "simulation"


# Repeated reap supports interrupted publication; an undispatched run has no workdir.


def test_reap_never_dispatched_ok_false_no_event_appended(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = "reapguard1"
    _write_file(module, "intent/brainstorm.md", "b1")
    before = store.read_events(module)
    r = _run_json(
        tmp_path, "reap", "--module", module, "--rule", "specification", "--run", "1"
    )
    assert r["ok"] is False
    assert store.read_events(module) == before


# ── B-group regression fixes (kernel-review disposition) ──────────────────


def test_dispatch_triage_without_sim_run_rejected(tmp_path, monkeypatch):
    # F8a root cause: cmd_dispatch must enforce a rule's declared mandatory params. Without
    # sim_run, the triage reap builds a diagnosis with subject.outcome_run=None -> schema
    # violation AFTER the outcome already landed -> half-reap. Reject the dispatch up front.
    monkeypatch.chdir(tmp_path)
    _write_file("m", "intent/brainstorm.md", "b1")
    r = _run_json(tmp_path, "dispatch", "--module", "m", "--rule", "simulation-triage")
    assert r["ok"] is False
    assert "sim_run" in r["error"]


def test_unknown_module_directory_is_a_hard_error(tmp_path, monkeypatch):
    """Module paths resolve against cwd, so an absent module directory is a wrong-cwd
    mistake, never a starting state — intent/brainstorm.md must already exist for anything to be
    dispatchable. Both verbs used to answer as if the module were merely empty: `status`
    invented an all-`missing` projection at exit 0, and `decide` reported an incomplete intent
    tree — which is exactly what a real module still waiting for its document reports."""
    monkeypatch.chdir(tmp_path)
    for verb in ("status", "decide"):
        r = _run(tmp_path, verb, "--module", "nosuch")
        assert r.returncode != 0, r.stdout
        assert "no module directory" in r.stderr
        assert str(tmp_path / "nosuch") in r.stderr


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
            "findings": [
                {"anchor": "a.v:1", "root_cause": "rtl-design", "reason": "why"}
            ],
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
    kinds = [e["type"] for e in store.read_events(module)]
    assert kinds.count("outcome") == 1 and kinds.count("diagnosis") == 1


def test_re_reap_old_triage_run_uses_its_own_sim_run(tmp_path, monkeypatch):
    # F8b: _derive_triage must key sim_run off the run being reaped, NOT the latest triage
    # dispatch. Re-reaping an older triage run while a newer one exists must label the
    # diagnosis subject with the OLD run's sim_run (mirrors the proof path's per-run lookup).
    monkeypatch.chdir(tmp_path)
    module = "rereap"
    _ss = {
        "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design", "reason": "why"}]
    }
    d1 = _dispatch_triage(tmp_path, module, sim_run=5)
    _write_triage_result(
        module,
        d1["workdir"],
        status="pass",
        stage_specific=_ss,
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
        stage_specific=_ss,
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
    diags = [e for e in store.read_events(module) if e["type"] == "diagnosis"]
    # Unchanged collection does not add a diagnosis.
    assert [d["subject"]["outcome_run"] for d in diags] == [5, 9]
    # Changed evidence in the old run still refers to that run's original subject.
    _write_triage_result(
        module,
        d1["workdir"],
        status="pass",
        stage_specific={
            "findings": [
                {
                    "anchor": "a.v:2",
                    "root_cause": "rtl-design",
                    "reason": "new evidence",
                }
            ]
        },
    )
    assert kernel.cmd_reap(module, "simulation-triage", d1["run"])["ok"]
    diags = [e for e in store.read_events(module) if e["type"] == "diagnosis"]
    assert diags[-1]["subject"]["outcome_run"] == 5


def test_dispatch_consumer_in_virgin_module_rejected(tmp_path, monkeypatch):
    # An input whose producer never ran is UNAVAILABLE. A manual dispatch of a
    # consumer (synthesis) in a virgin module (rtl-design/specification never ran) must be
    # rejected; else the run records an empty input table -> a vacuously-valid proof forever.
    monkeypatch.chdir(tmp_path)
    module = "virgin"
    _write_file(module, "intent/brainstorm.md", "b1")
    r = _run_json(tmp_path, "dispatch", "--module", module, "--rule", "synthesis")
    assert r["ok"] is False
    assert "not available" in r["error"]


# ── C-group regression fixes (low-risk corners, kernel-review disposition) ──


def test_outputs_name_the_artifacts_that_are_the_evidence(tmp_path, monkeypatch):
    # The report-class products ARE the evidence, so the outcome must name
    # the canonical result.json AND every artifacts[] path — recording only result.json
    # truncates the audit trail. `outputs` carries them with their fingerprints, which is
    # why the proof no longer repeats the bare paths beside it.
    monkeypatch.chdir(tmp_path)
    _write_file("m", "intent/brainstorm.md", "b1")
    _dispatch_write_reap(tmp_path, "m", "specification", _STAGE_FILES["specification"])
    _, outcome = facts.proof_outcome(store.read_events("m"), "specification")
    outs = outcome["outputs"]
    assert "Design/specification/result.json" in outs
    assert any(o.endswith("design.md") for o in outs)  # an artifact beyond result.json
    assert all(v.startswith(("sha256:", "merkle:")) for v in outs.values())
    proof = next(p for p in outcome["proofs"] if p["name"] == "specification")
    assert "evidence" not in proof


def test_unresolved_triage_without_reason_is_incomplete(tmp_path, monkeypatch):
    # An unresolved diagnosis needs a reason; an empty object is incomplete.
    monkeypatch.chdir(tmp_path)
    module = "d4a"
    d = _dispatch_triage(tmp_path, module, sim_run=1)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={"findings": []},
    )  # no findings
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


# ── reap temporal-integrity check (room-birth hygiene) ────────────────────────
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
    _write_file(module, "intent/brainstorm.md", "b1")
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
    assert r == {
        "ok": True,
        "rule": "specification",
        "run": 1,
        "verdict": "blocked",
        "reason": "stale_result",
    }
    outcome = store.read_events(module)[-1]
    assert outcome["reason"] == "stale_result"
    assert outcome["outputs"] == {} and outcome["proofs"] == []
    canonical = store.module_root(module) / "Design" / "specification"
    assert not (canonical / "result.json").exists()  # blocked never promotes


def test_reap_same_second_produced_at_not_misjudged(tmp_path, monkeypatch):
    # Skill finalizers stamp second-resolution UTC while the kernel dispatch ts carries
    # microseconds: a sub-second run's produced_at can equal the dispatch second exactly.
    # The check floors the dispatch ts, so the boundary case must reap pass, not stale.
    monkeypatch.chdir(tmp_path)
    module = "boundary1"
    _write_file(module, "intent/brainstorm.md", "b1")
    d = _run_json(tmp_path, "dispatch", "--module", module, "--rule", "specification")
    dispatch_ts = store.read_events(module)[-1]["ts"]  # %Y-%m-%dT%H:%M:%S.%fZ
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
    _write_file(module, "intent/brainstorm.md", "b1")
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
    assert store.read_events(module)[-1]["reason"] == "produced_at_unparseable"


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
    # cold specification dispatch → workdir has dispatch.json with the intent location
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m").mkdir(parents=True)
    (tmp_path / "m" / "intent").mkdir(parents=True, exist_ok=True)
    (tmp_path / "m" / "intent" / "brainstorm.md").write_text("bs")
    r = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        "m",
        "--rule",
        "specification",
    )
    wd = tmp_path / "m" / r["workdir"]
    table = json.loads((wd / "dispatch.json").read_text())["inputs"]
    assert table["intent"] == str((tmp_path / "m" / "intent").resolve())


def test_dispatch_carries_author_previous_round(tmp_path, monkeypatch):
    # seed a canonical specification product, then re-dispatch → carried into new workdir
    monkeypatch.chdir(tmp_path)
    canon = tmp_path / "m" / "Design" / "specification"
    canon.mkdir(parents=True)
    (canon / "design.md").write_text("prev")
    (tmp_path / "m" / "intent").mkdir(parents=True, exist_ok=True)
    (tmp_path / "m" / "intent" / "brainstorm.md").write_text("bs")
    r = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        "m",
        "--rule",
        "specification",
    )
    wd = tmp_path / "m" / r["workdir"]
    assert (wd / "design.md").read_text() == "prev"


def test_dispatch_injects_no_upstream_byte_copy(tmp_path, monkeypatch):
    # A transformer dispatch writes ONLY dispatch.json — the upstream RTL is
    # injected as a location, never copied into the workdir. (Half b — editing canonical
    # invalidates the proof — is covered by test_facts_freshness input-change tests.)
    monkeypatch.chdir(tmp_path)
    # seed enough upstream so synthesis is dispatchable: specification then rtl-design,
    # each taken through a real dispatch+result+reap (mirrors _dispatch_write_reap /
    # _build_full_chain) so their outcomes are recorded and rule_available sees them.
    _write_file("m", "intent/brainstorm.md", "bs")
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
    wd = tmp_path / "m" / r["workdir"]
    assert (wd / "dispatch.json").is_file()
    assert not (wd / "top.v").exists()  # upstream RTL injected, not copied


def test_dispatch_proof_inputs_excludes_self_carry(tmp_path, monkeypatch):
    # An author's carried self-products are NOT in Rule.inputs, so the dispatch event's
    # recorded input table (proof.inputs source) never contains them — dropping/editing a
    # carried product cannot stale the author's fresh proof.
    monkeypatch.chdir(tmp_path)
    canon = tmp_path / "m" / "Design" / "specification"
    canon.mkdir(parents=True)
    (canon / "design.md").write_text(
        "prev"
    )  # a self-PRODUCT (output), carried, not an input
    (tmp_path / "m" / "intent").mkdir(parents=True, exist_ok=True)
    (tmp_path / "m" / "intent" / "brainstorm.md").write_text("bs")
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
        for ln in (tmp_path / "m" / "events.jsonl").read_text().splitlines()
    ]
    disp = [e for e in events if e["type"] == "dispatch"][-1]
    assert set(disp["inputs"]) == {"intent"}  # design.md (self-product) absent


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


def test_a_read_only_verb_freezes_the_intent_tree(tmp_path, monkeypatch):
    """The enforcement hangs off the CLI, not off an event append: an operator poking at a
    reaped module reaches for `status`, which writes nothing, and that is exactly the window
    in which a reader's __pycache__ invalidated every proof."""
    monkeypatch.chdir(tmp_path)
    module = "frozen"
    _write_file(module, "intent/reference/model.py", "X = 1\n")
    ref = store.module_root(module) / "intent" / "reference" / "model.py"
    assert ref.stat().st_mode & 0o200  # the test wrote it, so it starts writable

    r = _run_json(tmp_path, "status", "--module", module)
    assert r["stages"]["specification"] == "missing"

    for p in (ref, ref.parent, store.module_root(module) / "intent"):
        assert not p.stat().st_mode & 0o200, p


def test_dispatch_rejects_non_object_params_before_allocating_run(tmp_path):
    module = tmp_path / "params"
    (module / "intent").mkdir(parents=True)
    (module / "intent/brainstorm.md").write_text("intent")
    for params in ("[]", "[1]", '"text"', "5"):
        reply = _run_json(
            tmp_path,
            "dispatch",
            "--module",
            str(module),
            "--rule",
            "specification",
            "--params",
            params,
        )
        assert reply["ok"] is False and "JSON object" in reply["error"]
        assert not (module / "Design").exists()
        assert not (module / "events.jsonl").exists()


def test_reap_reports_non_object_result_schema_error(tmp_path):
    module = tmp_path / "result-type"
    (module / "intent").mkdir(parents=True)
    (module / "intent/brainstorm.md").write_text("intent")
    dispatched = _run_json(
        tmp_path, "dispatch", "--module", str(module), "--rule", "specification"
    )
    (Path(dispatched["workdir"]) / "result.json").write_text("[]")
    reply = _run_json(
        tmp_path,
        "reap",
        "--module",
        str(module),
        "--rule",
        "specification",
        "--run",
        "1",
    )
    assert reply["verdict"] == "blocked"
    assert "object" in reply["reason"]
    assert store.read_events(str(module))[-1]["reason"] == reply["reason"]


@pytest.mark.parametrize("source", ["stage", "triage", "decision"])
def test_cli_local_tb_repair_preserves_upstream_and_resumes(
    tmp_path, monkeypatch, source
):
    """Replay the FSA endend failure through real dispatch/reap/decide, not a mocked scheduler."""
    monkeypatch.chdir(tmp_path)
    module = "local-repair"
    _build_full_chain(tmp_path, module)
    upstream = store.module_root(module) / "Design/rtl-design/src"
    before = facts.fingerprint(upstream)
    d = _run_json(tmp_path, "dispatch", "--module", module, "--rule", "simulation")
    result = {
        "stage": "simulation",
        "produced_at": _now_iso(),
        "status": "fail",
        "artifacts": [
            {"path": p} for p in [*_STAGE_FILES["simulation"], "tb/uvm/check.sv"]
        ],
        "stage_specific": {
            "fix_owner": "simulation",
            "fail_reason": "VCS syntax error: endend in the simulation-owned checker",
        },
    }
    if source != "stage":
        result["stage_specific"].pop("fix_owner")
    _write_file(module, d["workdir"] + "/tb/uvm/check.sv", "endend\n")
    _write_file(module, d["workdir"] + "/result.json", json.dumps(result))
    assert (
        _run_json(
            tmp_path,
            "reap",
            "--module",
            module,
            "--rule",
            "simulation",
            "--run",
            str(d["run"]),
        )["verdict"]
        == "fail"
    )
    if source == "triage":
        triage = _dispatch_triage(tmp_path, module, sim_run=d["run"])
        _write_triage_result(
            module,
            triage["workdir"],
            status="pass",
            stage_specific={
                "findings": [
                    {
                        "anchor": "tb/uvm/check.sv:1",
                        "root_cause": "simulation",
                        "reason": "endend is a TB syntax error",
                    }
                ]
            },
        )
        assert (
            _run_json(
                tmp_path,
                "reap",
                "--module",
                module,
                "--rule",
                "simulation-triage",
                "--run",
                str(triage["run"]),
            )["verdict"]
            == "pass"
        )
    elif source == "decision":
        assert _run_json(
            tmp_path,
            "diagnose",
            "--module",
            module,
            "--id",
            "review",
            "--subject-proof",
            "simulation",
            "--subject-run",
            str(d["run"]),
            "--attribution",
            "simulation",
            "--fix-owner",
            "simulation",
            "--provenance",
            "reviewer",
            "--reason",
            "TB syntax error",
        )["ok"]
    action = _run_json(tmp_path, "decide", "--module", module)
    assert (action["action"], action["rule"]) == ("DISPATCH", "simulation")
    repair = _run_json(tmp_path, *action["dispatch_args"])
    assert repair["ok"]
    dispatch = json.loads(
        (store.module_root(module) / repair["workdir"] / "dispatch.json").read_text()
    )
    assert any(f"runs/{d['run']}/result.json" in p for p in dispatch["caused_by"])
    assert _run_json(tmp_path, "decide", "--module", module)["action"] == "YIELD"
    _write_file(module, repair["workdir"] + "/tb/uvm/check.sv", "// repaired checker\n")
    result.update(status="pass", produced_at=_now_iso(), stage_specific={})
    _write_file(module, repair["workdir"] + "/result.json", json.dumps(result))
    assert (
        _run_json(
            tmp_path,
            "reap",
            "--module",
            module,
            "--rule",
            "simulation",
            "--run",
            str(repair["run"]),
        )["verdict"]
        == "pass"
    )
    status = _run_json(tmp_path, "status", "--module", module)
    assert status["stages"]["simulation"] == "valid"
    assert facts.fingerprint(upstream) == before
    assert _run_json(tmp_path, "decide", "--module", module)["action"] != "ESCALATE"


@pytest.mark.parametrize("source", ["decision", "triage"])
def test_dispatch_preserves_a_diagnosis_reason_from_any_source(tmp_path, source):
    module = tmp_path / "module"
    _write_file(str(module), "intent/brainstorm.md", "fixture intent")
    reason = "Retain the specified clock period while repairing the constraint."
    store.append_event(
        str(module),
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "synthesis", "outcome_run": 1},
            "attribution": "specification",
            "fix_owner": "specification",
            "source": source,
            "provenance": "fixture reviewer",
            "reason": reason,
        },
        TS,
    )
    result = kernel.cmd_dispatch(str(module), "specification", ["d1"])
    assert result["ok"]
    dispatch = json.loads((Path(result["workdir"]) / "dispatch.json").read_text())
    assert dispatch["reasons"] == [reason]


def test_blocked_rechecks_never_reuse_an_earlier_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "baseline")
    assert kernel.cmd_signoff("baseline", "fixture", "accept baseline")["ok"]
    for rule in rules.FORWARD_PRIORITY:
        for cause in ("missing", "unparseable"):
            module = f"{rule}-{cause}"
            shutil.copytree("baseline", module)
            d = kernel.cmd_dispatch(module, rule, None)
            wd = Path(d["workdir"])
            if cause == "unparseable":
                (wd / "result.json").write_text("{incomplete json")
            result = kernel.cmd_reap(module, rule, d["run"])
            assert result["verdict"] == "blocked" and result["reason"] == cause
            events = store.read_events(module)
            assert facts.proof_outcome(events, rule) is None
            assert not facts.proof_valid(module, events, rule)
            assert not facts.signed_off(module, events)
            assert not kernel.cmd_signoff(module, "fixture", "incomplete delivery")[
                "ok"
            ]
            action = kernel.schedule.decide(module, closing=True)
            assert action["action"] == "DISPATCH" and action["rule"] == rule
            # Correct and collect the same attempt; no historical event is edited.
            canonical = Path("baseline").joinpath(*rules.workdir_root(rule))
            env = json.loads((canonical / "result.json").read_text())
            for a in env["artifacts"]:
                source, target = canonical / a["path"], wd / a["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, target)
            env["produced_at"] = _now_iso()
            (wd / "result.json").write_text(json.dumps(env))
            assert kernel.cmd_reap(module, rule, d["run"])["verdict"] == "pass"
            assert kernel.schedule.decide(module)["action"] == "DONE"
            assert not facts.signed_off(module, store.read_events(module))


def test_triage_recollection_completes_interrupted_diagnosis_recording(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    module = "interrupted-triage"
    d = _dispatch_triage(tmp_path, module, sim_run=4)
    _write_triage_result(
        module,
        d["workdir"],
        status="pass",
        stage_specific={
            "findings": [
                {
                    "anchor": "a.v:1",
                    "root_cause": "rtl-design",
                    "reason": "implementation defect",
                },
                {
                    "anchor": "tb.sv:2",
                    "root_cause": "simulation",
                    "reason": "independent checker defect",
                },
            ]
        },
    )
    append = store.append_event

    def interrupted(module, event, ts):
        if event["type"] == "diagnosis" and event.get("fix_owner") == "simulation":
            raise OSError("recording interrupted")
        return append(module, event, ts)

    monkeypatch.setattr(store, "append_event", interrupted)
    with pytest.raises(OSError, match="recording interrupted"):
        kernel.cmd_reap(module, "simulation-triage", d["run"])
    first = [e for e in store.read_events(module) if e["type"] == "diagnosis"]
    assert len(first) == 1
    monkeypatch.setattr(store, "append_event", append)
    for _ in range(2):
        assert (
            kernel.cmd_reap(module, "simulation-triage", d["run"])["verdict"] == "pass"
        )
    diags = [e for e in store.read_events(module) if e["type"] == "diagnosis"]
    assert len(diags) == 2 and diags[0] == first[0]
    assert {d["fix_owner"] for d in diags} == {"rtl-design", "simulation"}
