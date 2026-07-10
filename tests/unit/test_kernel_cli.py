"""CLI tests for framework/scripts/kernel.py (subprocess idiom, test_state.py::TestCLI).

Exercises the kernel ENTRY POINT (argparse wiring -> verb handlers -> facts/schedule/
store composition), not the underlying algorithms already covered by
test_facts_*/test_rules/test_route/test_schedule/test_store.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = str(ROOT / "framework" / "scripts" / "kernel.py")
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import rules  # noqa: E402


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
        "produced_at": "2026-07-10T00:00:00Z",
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
        "rtl_filelist.f": "top.v",
        "tb/uvm/dummy.sv": "// tb",
    },
    "power-analysis": {
        "reports_ptpx/run1/power_hier.rpt": "power ok",
    },
}


def _build_full_chain(tmp_path, module, *, epoch_first):
    """Dispatch+write+reap every stage but frontend-signoff, in FORWARD_PRIORITY
    order, leaving every oracle unpinned (proposed). `epoch_first` controls whether
    the epoch anchor precedes (post-anchor valid chain) or is absent entirely."""
    _write_file(module, "brainstorm.md", "b1")
    if epoch_first:
        e = _run_json(
            tmp_path,
            "epoch",
            "--module",
            module,
            "--objective",
            "signoff",
            "--provenance",
            "andrew",
            "--reason",
            "start signoff epoch",
        )
        assert e["ok"] is True, e
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


def test_epoch_then_signoff_decide_gates_on_proposed_oracle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "gate1", epoch_first=True)
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


def test_signoff_bypass_blocked_no_epoch_hard_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "gate2", epoch_first=False)
    r = _run(
        tmp_path,
        "dispatch",
        "--module",
        "gate2",
        "--rule",
        "frontend-signoff",
        "--objective",
        "signoff",
    )
    assert r.returncode != 0
    assert "open an epoch first" in r.stderr
    assert r.stdout == ""


def test_signoff_bypass_blocked_epoch_open_proposed_oracle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _build_full_chain(tmp_path, "gate3", epoch_first=True)
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
