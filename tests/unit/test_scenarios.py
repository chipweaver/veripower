"""Code-level scenario replays (spec §6) against the REAL kernel.

Template: test_state.py::TestFullLoop (multi-round dispatch/reap loop). Idioms are
reused verbatim from the two landed kernel suites the brief names:
  * test_schedule.py — in-process event construction (facts.append_event) with real
    fingerprints and a per-run content marker so a rebuild genuinely drifts bytes;
  * test_kernel_cli.py — real kernel verbs (kernel.cmd_dispatch / cmd_reap with a
    crafted, schema-valid result.json) so triage mints a real diagnosis + a canonical
    result.json, and dispatch writes a real dispatch.json.
No mocks: every proof, fingerprint, scope, and diagnosis is produced by the
landed facts/schedule/kernel code over a real asic/<module>/ tree.

Each scenario replays a multi-step pipeline flow and asserts the BINDING per-step
assertions from task-D1-brief.md. Scenario replays against already-landed semantics
are GREEN-first by construction (the kernel is built + task-reviewed); where a step
demands RED evidence that a change actually bit, the test pins a baseline BEFORE the
mutation and asserts the flip (e.g. Step 1 checks the scaffold consumer really goes
invalid; Step 2/2b assert the edited file's fingerprint actually changed).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import kernel  # noqa: E402
import rules  # noqa: E402
import schedule  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def _now_iso() -> str:
    """Fresh second-resolution UTC stamp (mirrors skill finalizers) so a mid-test
    result.json passes the reap temporal-integrity check."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── test_schedule.py helper idioms (copied verbatim — real event logs) ──────────

_OUTPUTS = {
    "specification": [
        "Design/specification/design.md",
        "Design/specification/child.md",
        "Design/specification/manifest.json",
        "Design/specification/ppa.json",
        "Design/specification/clocks.json",
        "Design/specification/features.json",
        "Design/specification/check-hints/c.json",
        "Design/specification/top-io.json",
        "Design/specification/interconnects.json",
        "Design/specification/constraints/top.sdc",
        "Design/specification/constraints/top.sgdc",
    ],
    "simulation-plan": [
        "Verification/simulation-plan/verification-plan.md",
        "Verification/simulation-plan/tb-scaffold.json",
        "Verification/simulation-plan/sequences.json",
        "Verification/simulation-plan/power-scenarios.json",
    ],
    "rtl-design": [
        "Design/rtl-design/matvec.v",
        "Design/rtl-design/rtl-files.json",
        "Design/rtl-design/constraint-annotations.json",
    ],
    "lint-cdc": ["Design/lint-cdc/lint-report.txt", "Design/lint-cdc/cdc-report.txt"],
    "synthesis": [
        "Design/synthesis/out/top_syn.v",
        "Design/synthesis/out/top_syn.sdc",
        "Design/synthesis/out/top_syn.sdf",
        "Design/synthesis/reports/qor.rpt",
    ],
    "timing-analysis": [
        "Design/timing-analysis/timing-report.txt",
    ],
    "simulation": [
        "Verification/simulation/case-results-summary.md",
        "Verification/simulation/env.sh",
        "Verification/simulation/rtl_filelist.f",
        "Verification/simulation/tb/uvm/agent.sv",
        "Verification/simulation/filelist.f",
    ],
    "power-analysis": [
        "Verification/power-analysis/reports_ptpx/S1/power_hier.rpt",
    ],
}


def _fp(module, rel):
    return facts.fingerprint(facts.module_root(module) / rel)


def _mk(module, rel, content):
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _dispatch(module, rule, run, inputs):
    facts.append_event(
        module,
        {
            "type": "dispatch",
            "rule": rule,
            "run": run,
            "workdir": f"{rule}/runs/{run}",
            "inputs": inputs,
            "params": {},
        },
        TS,
    )


def _outcome(module, rule, run, verdict, outputs, proofs, **extra):
    ev = {
        "type": "outcome",
        "rule": rule,
        "run": run,
        "verdict": verdict,
        "outputs": outputs,
        "proofs": proofs,
        "tool_versions": {},
    }
    ev.update(extra)
    facts.append_event(module, ev, TS)


def _recorded_inputs(module, rule, extra=()):
    root = facts.module_root(module)
    rec = {}
    for globs in rules.RULES[rule].inputs.values():
        for g in globs:
            if rules.producer_of(g) == rule:
                continue
            for p in sorted(root.glob(g)):
                if p.is_file():
                    rec[str(p.relative_to(root))] = facts.fingerprint(p)
    for rel in extra:
        rec[rel] = _fp(module, rel)
    return rec


def _valid(module, rule, run, *, tag=None, out_content=None):
    """Dispatch+pass `rule`: write its declared outputs (content per `out_content`
    override else the run-tagged default), record inputs/outputs at current-disk
    fingerprints, emit a passing same-name proof carrying the rule's declared oracle."""
    r = rules.RULES[rule]
    marker = tag if tag is not None else f"r{run}"
    for rel in _OUTPUTS[rule]:
        content = (out_content or {}).get(rel, f"{rule}:{rel}:{marker}")
        _mk(module, rel, content)
    inputs = _recorded_inputs(module, rule)
    outputs = {rel: _fp(module, rel) for rel in _OUTPUTS[rule]}
    _dispatch(module, rule, run, inputs)
    _outcome(
        module,
        rule,
        run,
        "pass",
        outputs,
        [
            {
                "name": rule,
                "verdict": "pass",
                "inputs": inputs,
                "oracle": {"ref": r.oracle[0], "grade": r.oracle[1]},
            }
        ],
    )


def _fail(module, rule, run, owner="auto"):
    """Dispatch+fail `rule`, recording current-disk inputs and no outputs.

    Also writes the canonical envelope naming a fix owner, because every stage contract
    requires one on a failure (`--fix-owner` on every failure) and the scheduler now stops
    the round on a failure nobody attributed. `owner="auto"` picks the first legal target;
    pass `owner=None` for the deliberately-unattributed case."""
    r = rules.RULES[rule]
    if owner == "auto":
        legal = sorted(rules.input_closure(rule), key=rules.FORWARD_PRIORITY.index)
        owner = legal[0] if legal else None
    ss = {"fail_reason": f"synthetic {rule} failure"}
    if owner:
        ss["fix_owner"] = owner
    _mk(
        module,
        "/".join(rules.workdir_root(rule)) + "/result.json",
        json.dumps({"status": "fail", "stage_specific": ss}),
    )
    inputs = _recorded_inputs(module, rule)
    _dispatch(module, rule, run, inputs)
    _outcome(
        module,
        rule,
        run,
        "fail",
        {},
        [
            {
                "name": rule,
                "verdict": "fail",
                "inputs": inputs,
                "oracle": {"ref": r.oracle[0], "grade": r.oracle[1]},
            }
        ],
    )


def _chain_through_simulation(module):
    """spec/plan/rtl proofs valid on disk — simulation's whole input closure."""
    _mk(module, "brainstorm.md", "b1")
    _valid(module, "specification", 1)
    _valid(module, "simulation-plan", 1)
    _valid(module, "rtl-design", 1)


# ── Step 1 ──────────────────────────────────────────────────────────────────────


def test_step1_scaffold_fix_keeps_upstream_proofs_valid(tmp_path, monkeypatch):
    """Round-1: after lint/synth/timing pass, a scaffold-only change re-invalidates
    ONLY the scaffold consumer (simulation) — lint/synth/timing proofs stay valid
    because none of them consume the plan sidecars."""
    monkeypatch.chdir(tmp_path)
    m = "round1"
    _mk(m, "brainstorm.md", "b1")
    for rule in (
        "specification",
        "simulation-plan",
        "rtl-design",
        "lint-cdc",
        "synthesis",
        "timing-analysis",
        "simulation",
    ):
        _valid(m, rule, 1)

    evs = facts.read_events(m)
    # baseline (non-vacuous): every proof valid before the scaffold change.
    for rule in ("lint-cdc", "synthesis", "timing-analysis", "simulation"):
        assert facts.proof_valid(m, evs, rule), f"{rule} should start valid"

    # scaffold-only change: drift simulation-plan's tb-scaffold.json.
    _mk(m, "Verification/simulation-plan/tb-scaffold.json", "scaffold-v2")
    evs = facts.read_events(m)

    # BINDING: lint / synth / timing proofs stay valid (no scaffold in their inputs).
    assert facts.proof_valid(m, evs, "lint-cdc")
    assert facts.proof_valid(m, evs, "synthesis")
    assert facts.proof_valid(m, evs, "timing-analysis")
    # only the scaffold consumer flips — proves the change actually bit.
    assert not facts.proof_valid(m, evs, "simulation")


def test_plan_sidecars_invalidate_only_their_own_consumer(tmp_path, monkeypatch):
    """The reason the plan's machine half is three files and not one.

    simulation reads tb-scaffold.json + sequences.json; power-analysis reads
    sequences.json + power-scenarios.json. A scenario-only edit must not cost a full
    compile + smoke + regress + coverage that cannot even observe it, and a testpoint-only
    edit must not cost a GLS + PT-PX run. Only sequences.json, which both genuinely read,
    invalidates both.
    """
    monkeypatch.chdir(tmp_path)
    m = "granularity"
    _mk(m, "brainstorm.md", "b1")
    for rule in (
        "specification",
        "simulation-plan",
        "rtl-design",
        "synthesis",
        "simulation",
        "power-analysis",
    ):
        _valid(m, rule, 1)
    base = "Verification/simulation-plan"

    def flip(sidecar, content):
        _mk(m, f"{base}/{sidecar}", content)
        evs = facts.read_events(m)
        return facts.proof_valid(m, evs, "simulation"), facts.proof_valid(
            m, evs, "power-analysis"
        )

    evs = facts.read_events(m)
    assert facts.proof_valid(m, evs, "simulation")  # baseline: both start valid
    assert facts.proof_valid(m, evs, "power-analysis")

    assert flip("power-scenarios.json", "[1]") == (True, False)
    _valid(m, "power-analysis", 2)  # re-establish before the next probe
    assert flip("tb-scaffold.json", "{}") == (False, True)
    _valid(m, "simulation", 2)
    assert flip("sequences.json", "[2]") == (False, False)


# ── Step 2 ──────────────────────────────────────────────────────────────────────


def _triage(module, sim_run, root_cause):
    """Real triage dispatch+reap: crafted schema-valid result.json -> a promoted
    canonical result.json + a minted diagnosis event (kernel _derive_triage)."""
    d = kernel.cmd_dispatch(module, "simulation-triage", None, {"sim_run": sim_run})
    assert d["ok"], d
    result = {
        "stage": "simulation-triage",
        "module": module,
        "produced_at": _now_iso(),
        "status": "pass",
        "artifacts": [],
        "stage_specific": {
            "analysis_state": "complete",
            # the attribution lives on the finding, and it must carry its anchor
            "advisory": {
                "findings": [{"anchor": "matvec.v:1", "root_cause": root_cause}],
            },
        },
    }
    _mk(module, f"{d['workdir']}/result.json", json.dumps(result))
    r = kernel.cmd_reap(module, "simulation-triage", d["run"])
    assert r["ok"] and r["verdict"] == "pass", r
    return d


def test_step2_repair_direct_hash_invariance_triage_handoff(tmp_path, monkeypatch):
    """Round-2: smoke fail -> triage(rtl-design, high) -> DISPATCH rtl-design ->
    the fix drifts only matvec.v -> the sim fail proof's recorded input drifts ->
    fail stale -> a repair forwards DIRECT to simulation, not rtl-design again."""
    monkeypatch.chdir(tmp_path)
    m = "round2"
    _chain_through_simulation(m)
    _valid(m, "lint-cdc", 1)  # a real lint proof, so (c) is non-vacuous
    rtl1 = facts.latest_outcome(facts.read_events(m), "rtl-design")["outputs"]

    _fail(m, "simulation", 1)  # smoke fail — records matvec.v@r1 as an input
    _triage(m, sim_run=1, root_cause="rtl-design")

    # fresh sim fail + reliable triage diagnosis -> DISPATCH the fix owner rtl-design.
    evs = facts.read_events(m)
    d1_id = [e for e in evs if e["type"] == "diagnosis"][-1]["id"]
    a = schedule.decide(m)
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    assert a["diagnosis_refs"] == [d1_id]
    assert a["caused_by"] == [["simulation", 1]]

    # (d) the triage analysis reaches rtl-design as data, not as a copy: `caused_by` names
    # the failing run's own envelope and `scope` carries the diagnosis's anchors. Nothing is
    # transcribed, and the fix owner never navigates to another stage itself.
    _mk(m, "Verification/simulation/runs/1/result.json", json.dumps({"status": "fail"}))
    dr = kernel.cmd_dispatch(
        m, "rtl-design", a["diagnosis_refs"], None, [("simulation", 1)]
    )
    assert dr["ok"], dr
    doc = json.loads(
        (facts.module_root(m) / dr["workdir"] / "dispatch.json").read_text()
    )
    assert doc["caused_by"] == ["Verification/simulation/runs/1/result.json"]
    assert doc["scope"] == ["matvec.v:1"]  # the triage finding's anchor

    # the fix lands (run 2): outcome changes ONLY matvec.v; filelist/README untouched.
    _mk(m, "Design/rtl-design/matvec.v", "rtl-design:matvec.v:FIX")  # drift on disk
    outputs = {rel: _fp(m, rel) for rel in _OUTPUTS["rtl-design"]}
    inputs = _recorded_inputs(m, "rtl-design")
    _outcome(
        m,
        "rtl-design",
        dr["run"],
        "pass",
        outputs,
        [
            {
                "name": "rtl-design",
                "verdict": "pass",
                "inputs": inputs,
                "oracle": {"ref": "semantic-review", "grade": "proposed"},
            }
        ],
    )
    rtl2 = facts.latest_outcome(facts.read_events(m), "rtl-design")["outputs"]

    # (b) minimal-edit / hash-invariance: untouched outputs' fingerprints unchanged;
    # the edited file's fingerprint DID change (proves the edit landed).
    for untouched in (
        "Design/rtl-design/rtl-files.json",
        "Design/rtl-design/constraint-annotations.json",
    ):
        assert rtl2[untouched] == rtl1[untouched]
    assert rtl2["Design/rtl-design/matvec.v"] != rtl1["Design/rtl-design/matvec.v"]

    # (a) the round re-verifies simulation — the fix owner has had its turn, so what is left
    # is to find out whether the fix worked. (c) lint went stale under the same RTL edit and
    # has no artifact edge to the failure, so the same turn opens it too — a `task`, sorted
    # first, costing the re-verify nothing.
    assert not facts.proof_valid(m, facts.read_events(m), "lint-cdc")  # lint IS stale
    opened = []
    while len(opened) < 2:
        a = schedule.decide(m)
        assert a["action"] == "DISPATCH", a
        opened.append(a["rule"])
        assert kernel.cmd_dispatch(m, a["rule"], None)["ok"]
    assert opened == ["lint-cdc", "simulation"]


# ── Step 2b ─────────────────────────────────────────────────────────────────────


def test_step2b_minimal_edit_on_directiveless_forward(tmp_path, monkeypatch):
    """A design.md prose tweak expires the specification proof and forces a forward
    re-dispatch with NO directive; the producer carries its prior outputs forward:
    every untouched output's fingerprint in the new outcome is byte-identical to the
    previous run's (§4.3 义务无条件 / §6 同式覆盖 — Step 2's minimal-edit invariant on a
    directive-LESS forward path)."""
    monkeypatch.chdir(tmp_path)
    m = "round2b"
    _mk(m, "brainstorm.md", "b1")
    _valid(m, "specification", 1)
    spec1 = facts.latest_outcome(facts.read_events(m), "specification")["outputs"]
    assert facts.proof_valid(m, facts.read_events(m), "specification")

    # a design.md prose tweak (hand-edit spec's own output) expires the proof.
    _mk(m, "Design/specification/design.md", "design v2 — one prose sentence added")
    assert not facts.proof_valid(m, facts.read_events(m), "specification")

    # forward re-dispatch with NO directive.
    a = schedule.decide(m)
    assert a["action"] == "DISPATCH" and a["rule"] == "specification"
    assert "caused_by" not in a  # a forward dispatch answers no failure

    # the producer carries prior outputs forward: it re-runs (run 2) re-emitting every
    # untouched artifact byte-for-byte (only design.md, the tweaked file, differs).
    inputs = _recorded_inputs(m, "specification")
    outputs = {rel: _fp(m, rel) for rel in _OUTPUTS["specification"]}
    _dispatch(m, "specification", 2, inputs)
    _outcome(
        m,
        "specification",
        2,
        "pass",
        outputs,
        [
            {
                "name": "specification",
                "verdict": "pass",
                "inputs": inputs,
                "oracle": {"ref": "spec-review", "grade": "proposed"},
            }
        ],
    )
    spec2 = facts.latest_outcome(facts.read_events(m), "specification")["outputs"]

    # BINDING: every untouched output byte-identical to the previous run.
    touched = "Design/specification/design.md"
    for rel in _OUTPUTS["specification"]:
        if rel == touched:
            continue
        assert spec2[rel] == spec1[rel], f"{rel} must carry forward (byte-identical)"
    assert spec2[touched] != spec1[touched]  # non-vacuous: the tweak actually bit


# ── Step 3 ──────────────────────────────────────────────────────────────────────


def test_step3_supersede_is_auditable(tmp_path, monkeypatch):
    """Round-3: a new diagnosis supersedes the old -> the old attribution goes inactive,
    rtl-design is re-dispatched on the new one, the supersede link on the ledger."""
    monkeypatch.chdir(tmp_path)
    m = "round3"
    _chain_through_simulation(m)
    _fail(m, "simulation", 1)

    # d1: original diagnosis blaming simulation-plan.
    facts.append_event(
        m,
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "simulation-plan",
            "fix_owner": "simulation-plan",
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "source": "triage",
        },
        TS,
    )
    # d2: a new diagnosis supersedes d1, re-attributing to rtl-design.
    facts.append_event(
        m,
        {
            "type": "diagnosis",
            "id": "d2",
            "supersedes": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "evidence": ["Verification/simulation-triage/runs/2/result.json"],
            "source": "triage",
        },
        TS,
    )

    evs = facts.read_events(m)
    sim_out = facts.latest_outcome(evs, "simulation")
    # the old attribution goes inactive (superseded); only d2 is active.
    active = schedule._active_diagnoses(evs, "simulation", sim_out)
    assert [d["id"] for d in active] == ["d2"]
    assert not any(d["id"] == "d1" for d in active)

    # rtl-design re-dispatched on the surviving diagnosis.
    a = schedule.decide(m)
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    assert a["diagnosis_refs"] == ["d2"]

    # the supersede link is on the ledger.
    d2 = next(e for e in evs if e["type"] == "diagnosis" and e["id"] == "d2")
    assert d2["supersedes"] == "d1"


# ── Step 4 ──────────────────────────────────────────────────────────────────────


def _timing_owed(module):
    """Is timing-analysis still owed a fix — i.e. has its owner not been dispatched since?"""
    evs = facts.read_events(module)
    assert schedule._latest_fail(evs, "timing-analysis") is not None
    fails = schedule._failures(module, evs)
    return any(f["rule"] == "timing-analysis" for f in schedule.owed(evs, fails))


def test_step4_multihop_synthesis_first_then_timing(tmp_path, monkeypatch):
    """Multi-hop: timing fail -> rtl-design fix -> synthesis rebuilds FIRST (timing's
    input _syn.v is a synthesis product), then timing re-verifies LAST. Driven purely by
    fail-freshness + condition 2 (no rework counter); never ESCALATE."""
    monkeypatch.chdir(tmp_path)
    m = "multihop"
    _mk(m, "brainstorm.md", "b1")
    _valid(m, "specification", 1)
    _valid(m, "rtl-design", 1)
    _valid(m, "synthesis", 1)
    _fail(
        m, "timing-analysis", 1, owner="synthesis"
    )  # a setup violation is synthesis's to fix

    assert _timing_owed(m)  # baseline (non-vacuous)

    # rtl-design fix lands -> synthesis proof invalid (its recorded RTL input drifts), but
    # _syn.v not yet regenerated, so timing's OWN inputs have not moved. The complaint stays
    # open: an upstream rebuild two hops away does not retract what timing reported.
    _valid(m, "rtl-design", 2)
    assert not facts.proof_valid(m, facts.read_events(m), "synthesis")
    assert _timing_owed(m)

    # the round rebuilds the producer (synthesis) — not timing, never ESCALATE. lint-cdc goes
    # first: the RTL edit staled it too, and synthesis's advisory edge waits on it.
    a = schedule.decide(m)
    assert a["action"] == "DISPATCH" and a["rule"] == "lint-cdc"
    _valid(m, "lint-cdc", 2)
    a = schedule.decide(m)
    assert a["action"] == "DISPATCH" and a["rule"] == "synthesis"

    # synthesis rebuilds -> _syn.v drifts -> timing's OWN recorded input now mismatches, and
    # this envelope names nobody, so there is no longer a specific thing to do about the
    # failure: it closes, and forward re-verification takes over.
    # synthesis has now had its turn, so timing is no longer owed anything and the forward
    # step re-verifies it.
    _valid(m, "synthesis", 2)
    assert facts.proof_valid(m, facts.read_events(m), "synthesis")
    assert not _timing_owed(m)

    # timing re-verifies LAST.
    b = schedule.decide(m)
    assert b["action"] == "DISPATCH" and b["rule"] == "timing-analysis"


# ── Step 5 ──────────────────────────────────────────────────────────────────────

_SPEC_MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"


def _derive_constraints(workdir):
    return subprocess.run(
        ["python3", str(_SPEC_MAIN), "derive-constraints", "--workdir", str(workdir)],
        capture_output=True,
        text=True,
        check=True,
    )


def _spec_workdir(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "m",
                "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
            }
        )
    )
    (tmp_path / "design.md").write_text(
        "# m Design\n\n#### 1.4.1 Top-Level IO\n\nPorts live in `top-io.json`.\n\n"
        "### 1.6 Clocks and Frequencies\n\nClock definitions live in `clocks.json`.\n"
    )
    (tmp_path / "top-io.json").write_text(
        json.dumps(
            [
                {
                    "name": "clk",
                    "direction": "input",
                    "width": 1,
                    "clock_domain": "clk",
                    "interface_group": "clk",
                    "role": "clock",
                },
                {
                    "name": "clk_io",
                    "direction": "input",
                    "width": 1,
                    "clock_domain": "clk_io",
                    "interface_group": "clk",
                    "role": "clock",
                },
                {
                    "name": "din",
                    "direction": "input",
                    "width": 8,
                    "clock_domain": "clk",
                    "interface_group": "cfg",
                    "protocol": "APB3",
                    "role": "data",
                },
            ]
        )
    )
    (tmp_path / "clocks.json").write_text(
        json.dumps(
            [
                {
                    "name": "clk",
                    "period_ns": 10.0,
                    "relationship": "primary",
                    "role": "primary clock",
                },
                {
                    "name": "clk_io",
                    "period_ns": 20.0,
                    "relationship": "async",
                    "role": "io clock",
                },
            ]
        )
    )
    return tmp_path


def test_step5_cold_regenerated_seed_byte_identical(tmp_path, monkeypatch):
    """Cold-start equivalence (unit-testable slice): delete the warm SGDC/SDC seed and
    re-derive — derive-constraints is deterministic, so the cold-regenerated seed is
    byte-identical to the warm one. (SpyGlass verdict-equality is an EDA-gated
    design-time obligation exercised via the F1 fixture, NOT asserted here.)"""
    wd = _spec_workdir(tmp_path)
    _derive_constraints(wd)
    warm_sgdc = (wd / "constraints" / "m.sgdc").read_bytes()
    warm_sdc = (wd / "constraints" / "m.sdc").read_bytes()
    # sanity: the seed is a non-trivial multi-clock SGDC (real CDC content).
    assert b"clock -name clk" in warm_sgdc

    # delete the warm cache seed, then cold-regenerate from the identical input.
    (wd / "constraints" / "m.sgdc").unlink()
    (wd / "constraints" / "m.sdc").unlink()
    _derive_constraints(wd)

    assert (wd / "constraints" / "m.sgdc").read_bytes() == warm_sgdc
    assert (wd / "constraints" / "m.sdc").read_bytes() == warm_sdc


def test_step5_lintcdc_dispatchable_and_waiver_never_cached(tmp_path, monkeypatch):
    """lint-cdc stays dispatchable after its warm SGDC seed is deleted (the seed is a
    derived warm-start, not a hard input). waiver.tcl is a promoted output whose
    producer_of==consumer self-reference still holds, but it is now carried
    (Rule.carry), not a declared input — no in∩out self-lock exemption applies to it
    anymore, with no separate cache declaration (the old Rule.cache field had no
    machine consumer and was removed)."""
    lint = rules.RULES["lint-cdc"]
    assert "scripts/waiver.tcl" in lint.outputs  # it IS a real promoted product
    input_globs = [g for gs in lint.inputs.values() for g in gs]
    assert rules.producer_of("Design/lint-cdc/scripts/waiver.tcl") == "lint-cdc"
    # the warm SGDC seed is NOT among lint-cdc's declared inputs — absence cannot gate.
    assert "Design/lint-cdc/scripts/constraints.sgdc" not in input_globs

    monkeypatch.chdir(tmp_path)
    m = "cold"
    _mk(m, "brainstorm.md", "b1")
    _valid(m, "specification", 1)  # writes the SGDC seed constraints/top.sgdc
    _valid(m, "rtl-design", 1)
    evs = facts.read_events(m)
    assert facts.rule_available(m, evs, "lint-cdc")  # dispatchable cold (no cache yet)

    # a prior lint run's warm cache seed exists, then is deleted -> still dispatchable.
    _mk(m, "Design/lint-cdc/scripts/constraints.sgdc", "cached-sgdc-v1")
    assert facts.rule_available(m, evs, "lint-cdc")
    (facts.module_root(m) / "Design/lint-cdc/scripts/constraints.sgdc").unlink()
    assert facts.rule_available(m, facts.read_events(m), "lint-cdc")


# ── The four dispatch shapes (dispatch.json) ─────────────────────────────────────


def _dispatch_doc(module, workdir):
    return json.loads(
        (facts.module_root(module) / workdir / "dispatch.json").read_text()
    )


def test_forward_redispatch_scope_names_the_drifted_inputs(tmp_path, monkeypatch):
    """Shape 2 — a forward re-dispatch: spec re-ran, drifting rtl-design's recorded inputs,
    so `scope` names exactly those files. That drift is what invalidated the proof, and only
    the kernel can compute it (the fingerprint table lives in the log)."""
    monkeypatch.chdir(tmp_path)
    m = "fwd-scope"
    _mk(m, "brainstorm.md", "b1")
    _valid(m, "specification", 1)
    _valid(m, "rtl-design", 1)  # records design.md/child/manifest at r1 fingerprints
    assert facts.proof_valid(m, facts.read_events(m), "rtl-design")

    _valid(m, "specification", 2, tag="r2")  # spec re-runs, re-promoting those files
    assert not facts.proof_valid(
        m, facts.read_events(m), "rtl-design"
    )  # inputs drifted

    d = kernel.cmd_dispatch(m, "rtl-design", None)
    assert d["ok"], d
    doc = _dispatch_doc(m, d["workdir"])
    assert "Design/specification/design.md" in doc["scope"]
    assert "Design/specification/child.md" in doc["scope"]
    assert "caused_by" not in doc and "reasons" not in doc


def test_first_dispatch_carries_no_narrowing_key(tmp_path, monkeypatch):
    """Shape 1 — a first delivery (no prior rtl-design outcome): `inputs` alone. The absent
    narrowing keys are what send the skill to full scope; it then tells that apart from a
    re-verify by whether the workdir already holds its own prior products."""
    monkeypatch.chdir(tmp_path)
    m = "fwd-first"
    _mk(m, "brainstorm.md", "b1")
    _valid(m, "specification", 1)  # spec present so rtl-design's inputs are available
    d = kernel.cmd_dispatch(m, "rtl-design", None)
    assert d["ok"], d
    assert list(_dispatch_doc(m, d["workdir"])) == ["inputs"]


def test_reverify_dispatch_carries_no_narrowing_key(tmp_path, monkeypatch):
    """Shape 4 — a re-verify: the oracle was reopened, so the proof is invalid with ZERO
    input drift. Same empty-narrowing shape as a first delivery, and the skill separates the
    two on disk: its prior products were carried in, so it re-derives its gate and rewrites
    nothing."""
    monkeypatch.chdir(tmp_path)
    m = "reverify"
    _mk(m, "brainstorm.md", "b1")
    _valid(m, "specification", 1)
    oref = rules.RULES["specification"].oracle[0]
    facts.append_event(
        m, {"type": "reopen", "pin_ref": oref, "reason": "re-examine"}, TS
    )
    assert not facts.proof_valid(m, facts.read_events(m), "specification")
    assert facts.stale_inputs(m, facts.read_events(m), "specification") == []

    d = kernel.cmd_dispatch(m, "specification", None)
    assert d["ok"], d
    assert list(_dispatch_doc(m, d["workdir"])) == ["inputs"]
    # carry_self brought the prior round's products in: that is the disk fact the skill
    # branches on, and it is what makes this shape distinguishable from a first delivery.
    assert (facts.module_root(m) / d["workdir"] / "design.md").is_file()


def test_repair_dispatch_names_the_failure_and_the_human_reasoning(
    tmp_path, monkeypatch
):
    """Shape 3 — a repair: `caused_by` names the failing run's own envelope, `scope` carries
    the diagnosis's fix_locus, and `reasons` carries a human author's reasoning verbatim.
    The envelope path is per-run, so a later run of the same stage cannot move it."""
    monkeypatch.chdir(tmp_path)
    m = "repair-shape"
    _mk(m, "brainstorm.md", "b1")
    _valid(m, "specification", 1)
    _valid(m, "rtl-design", 1)
    _fail(m, "synthesis", 1)
    # reap promotes a failing run's envelope, so in production this path always exists.
    _mk(m, "Design/synthesis/runs/1/result.json", json.dumps({"status": "fail"}))
    r = kernel.cmd_diagnose(
        m,
        "diag-unit",
        "synthesis",
        1,
        "specification",
        "specification",
        [str(facts.module_root(m).resolve() / "Design/specification/ppa.json")],
        ["Design/synthesis/runs/1/reports/area.rpt"],
        "operator",
        "the area target's unit is wrong, not the RTL",
        None,
    )
    assert r["ok"], r
    # an absolute fix_locus the operator typed is rebased, so dispatch.json stays single-basis
    diag = [e for e in facts.read_events(m) if e["type"] == "diagnosis"][-1]
    assert diag["fix_locus"] == ["Design/specification/ppa.json"]

    d = kernel.cmd_dispatch(m, "specification", ["diag-unit"], None, [("synthesis", 1)])
    assert d["ok"], d
    doc = _dispatch_doc(m, d["workdir"])
    assert doc["caused_by"] == ["Design/synthesis/runs/1/result.json"]
    assert doc["scope"] == ["Design/specification/ppa.json"]
    assert doc["reasons"] == ["the area target's unit is wrong, not the RTL"]
    ev = next(
        e
        for e in reversed(facts.read_events(m))
        if e["type"] == "dispatch" and e["rule"] == "specification"
    )
    assert ev["caused_by"] == [["synthesis", 1]]


def test_repair_dispatch_rejects_an_unresolvable_channel(tmp_path, monkeypatch):
    """Both rework channels fail closed. A dangling --caused-by would hand the worker a path
    it cannot open; an unknown --diagnosis-refs would drop that diagnosis's fix_locus and
    reasoning silently, which is the loss §3.3 forbids."""
    monkeypatch.chdir(tmp_path)
    m = "repair-guard"
    _mk(m, "brainstorm.md", "b1")
    _valid(m, "specification", 1)
    r = kernel.cmd_dispatch(m, "rtl-design", None, None, [("synthesis", 9)])
    assert not r["ok"] and "no result.json" in r["error"]
    r = kernel.cmd_dispatch(m, "rtl-design", ["diag-nope"], None)
    assert not r["ok"] and "unknown diagnosis ref" in r["error"]
    # neither attempt allocated a run
    assert facts.runs_of(facts.read_events(m), "rtl-design") == 0
