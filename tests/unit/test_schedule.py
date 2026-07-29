import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import rules  # noqa: E402
import schedule  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def _write(module, rel, text):
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return facts.fingerprint(p)


def _dispatch(module, rule, run, inputs, objective="delivery"):
    facts.append_event(
        module,
        {
            "type": "dispatch",
            "rule": rule,
            "run": run,
            "workdir": f"{rule}/runs/{run}",
            "inputs": inputs,
            "params": {},
            "objective": objective,
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


def test_cold_start_dispatches_specification(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "specification"
    assert a["execution"] == "main-thread"


def test_wake_reap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _dispatch(
        "m",
        "specification",
        1,
        {"brainstorm.md": facts.fingerprint(facts.module_root("m") / "brainstorm.md")},
    )
    # workdir result.json present -> REAP even without wake (收口 branch)
    rj = facts.module_root("m") / "specification" / "runs" / "1" / "result.json"
    rj.parent.mkdir(parents=True, exist_ok=True)
    rj.write_text("{}")
    a = schedule.decide("m")
    assert a["action"] == "REAP" and a["rule"] == "specification" and a["run"] == 1


def test_in_flight_no_result_yields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"brainstorm.md": "sha256:x"})
    a = schedule.decide("m")
    assert a["action"] == "YIELD"
    assert a["in_flight"] == [{"rule": "specification", "run": 1, "has_result": False}]


def test_fresh_failure_with_reliable_triage_dispatches_fix_owner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # simulation fails fresh; a high-confidence triage diagnosis points at rtl-design.
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "confidence": "high",
            "source": "triage",
        },
        TS,
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    assert a["needs_directive"] is True and a["triage_forward"] is True
    assert a["diagnosis_refs"] == ["d1"]


def test_fresh_failure_self_pointing_escalates(tmp_path, monkeypatch):
    # A3 regression: confidence=high but the attribution points at the failed rule's own
    # judge (root_cause=simulation, no fix_owner) -> a 现成归因 that is UNRELIABLE ->
    # ESCALATE citing it as a candidate. NOT re-dispatch triage, NOT auto-rebuild.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")  # helper: spec/plan/rtl proofs valid on disk
    _sim_fail("m", run=1)  # helper: fresh simulation fail outcome
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "simulation",  # oracle side — no fix_owner
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "confidence": "high",
            "source": "triage",
        },
        TS,
    )
    a = schedule.decide("m")
    assert a["action"] == "ESCALATE"
    assert a["candidates"][0]["diagnosis"] == "d1"
    # and it stays escalated (no triage re-dispatch loop) on the next call
    assert schedule.decide("m")["action"] == "ESCALATE"


def test_repair_after_fix_lands_redispatches_failed_rule_not_fix_owner(
    tmp_path, monkeypatch
):
    # spec §3.4 case: fix changes matvec.v -> simulation fail proof stale -> forward
    # re-dispatches simulation (re-verify), NOT rtl-design again.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)  # records the OLD matvec.v version
    _valid("m", "rtl-design", 2, tag="fix")  # fix lands: matvec.v drifts -> fail stale
    a = schedule.decide("m", objective="repair")
    assert a["action"] == "DISPATCH" and a["rule"] == "simulation"


def test_blocked_goes_forward_no_escalate(tmp_path, monkeypatch):
    # blocked outcome -> no proof -> step 2 re-dispatches the rule; never step 1, never ESCALATE.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"brainstorm.md": _fp("m", "brainstorm.md")})
    _outcome("m", "specification", 1, "blocked", {}, [], reason="crash")
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "specification"


def test_fresh_lintcdc_self_describing_failure_routes_by_category(
    tmp_path, monkeypatch
):
    # Fix round 1: the self-describing-failure branch — route.route composed inline on
    # stage_specific read from the failed rule's CANONICAL result.json (_route_kwargs).
    # lint-cdc fresh fail, failures[0].category=rtl_cdc -> input-provenance target
    # rtl-design (U4), dispatched with needs_directive.
    monkeypatch.chdir(tmp_path)
    _mk("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "lint-cdc", 1)  # fresh: closure (spec+rtl) valid, inputs match disk
    # before the canonical result.json exists, route gets failures=None -> ESCALATE
    # (proves the branch genuinely reads the file, not a vacuous pass)
    pre = schedule.decide("m")
    # reason now prefixes the failed rule (F-4 disambiguation)
    assert pre["action"] == "ESCALATE" and pre["reason"] == "lint-cdc: lint_no_category"
    _mk(
        "m",
        "Design/lint-cdc/result.json",
        json.dumps(
            {
                "stage_specific": {
                    "failure_kind": "tooling",
                    "failures": [
                        {"category": "rtl_cdc", "error_summary": "clock crossing"}
                    ],
                    "fail_reason": "cdc",
                }
            }
        ),
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    assert a["needs_directive"] is True


def test_fresh_rtldesign_spec_locus_high_dispatches_specification(
    tmp_path, monkeypatch
):
    # D4: _route_kwargs now feeds stage_specific.semantic_gate (D2's write) into
    # route.route (D3's rtl-design branch) — a fresh rtl-design fail whose semantic
    # gate pins a high-confidence spec-locus intent defect routes upstream to
    # specification instead of falling into the unrouted escalate.
    monkeypatch.chdir(tmp_path)
    _mk("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _fail("m", "rtl-design", 1)  # fresh: input closure (specification) valid
    # before the canonical result.json carries semantic_gate, route sees loci=None ->
    # ESCALATE (proves the branch genuinely reads the file, not a vacuous pass)
    pre = schedule.decide("m")
    assert pre["action"] == "ESCALATE" and pre["reason"] == "rtl-design: rtl_unrouted"
    _mk(
        "m",
        "Design/rtl-design/result.json",
        json.dumps(
            {
                "stage_specific": {
                    "semantic_gate": {
                        "loci": {"spec": ["c1"], "rtl": []},
                        "spec_confidence": "high",
                    },
                    "fail_reason": "semantic gate: spec-rooted intent defect — c1",
                }
            }
        ),
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "specification"
    assert a["needs_directive"] is True


def test_delivery_no_overtake_but_repair_direct(tmp_path, monkeypatch):
    # same disk+ledger: delivery does not dispatch synthesis while lint-cdc in flight
    # (advisory prereq); repair dispatches synthesis even if lint-cdc stale.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "simulation-plan", 1)
    _valid("m", "rtl-design", 1)
    _valid("m", "synthesis", 1)
    _reopen("m", "dc-shell")  # synthesis proof invalid (RTL bytes unchanged)
    _dispatch(
        "m", "lint-cdc", 1, {}
    )  # lint-cdc in flight (advisory prereq of synthesis)
    _fail(
        "m", "timing-analysis", 1
    )  # stale fail -> repair target whose rebuild is synthesis
    d = schedule.decide("m")
    # pin the POSITIVE outcome, not just "not synthesis" (which any action satisfies).
    # synthesis is held by the no-overtake gate (advisory prereq lint-cdc in flight); the
    # lowest-priority eligible rule is simulation (missing proof, its prereqs rtl/plan valid).
    assert d["action"] == "DISPATCH" and d["rule"] == "simulation"
    assert d["rule"] != "synthesis"  # the no-overtake invariant under test
    r = schedule.decide("m", objective="repair")
    assert r["action"] == "DISPATCH" and r["rule"] == "synthesis"


def test_signoff_all_valid_pinned_done(tmp_path, monkeypatch):
    # all 8 stage proofs valid with every oracle pinned -> objective=signoff is DONE,
    # meaning "the gate is clear, go stamp".
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1, oracle_grades=_PIN_ALL)
    assert schedule.decide("m", objective="signoff")["action"] == "DONE"


def test_signoff_objective_is_not_a_delivery_alias(tmp_path, monkeypatch):
    # required_proofs is IDENTICAL for delivery and signoff, so the gate at decide's DONE
    # point is the only thing that distinguishes them. Without it, signoff would silently
    # degrade to a delivery alias and report DONE with the trust boundary never consulted.
    # Same log, same proofs, opposite verdicts — that delta IS the objective.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)  # default (proposed) grades — gate must refuse
    assert schedule.required_proofs(
        facts.read_events("m"), "delivery"
    ) == schedule.required_proofs(facts.read_events("m"), "signoff")
    assert schedule.decide("m", objective="delivery")["action"] == "DONE"
    assert schedule.decide("m", objective="signoff")["action"] == "ESCALATE"


def test_signoff_gate_blocks_on_proposed_oracle(tmp_path, monkeypatch):
    # Every stage proof valid; default oracle grades leave several "proposed". The reason
    # must name the FIRST offender in FORWARD_PRIORITY order (specification) —
    # deterministic, never hash-seed-dependent set order.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("proposed", 1)
    a = schedule.decide("proposed", objective="signoff")
    assert a["action"] == "ESCALATE"
    assert a["reason"] == "signoff blocked: specification oracle is proposed (pin it)"


def test_signoff_gate_reads_live_pin_without_rereap(tmp_path, monkeypatch):
    # A pin recorded AFTER a proof's reap (its outcome snapshot still reads "proposed")
    # lifts the signoff gate immediately, with NO re-reap: the gate reads the live grade
    # (facts.oracle_grade over the current event log), not the reap-time snapshot.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)  # default (proposed) grades
    assert (
        facts.signoff_gate("m", facts.read_events("m"))
        == "signoff blocked: specification oracle is proposed (pin it)"
    )
    # Pin every proposed oracle after the fact; no proof is re-reaped.
    for rule in rules.FORWARD_PRIORITY:
        if rules.RULES[rule].oracle[1] == "proposed":
            _pin("m", rule)
    assert facts.signoff_gate("m", facts.read_events("m")) is None


# --- §6-mandated coverage (each maps to a spec §6 bullet) ---


def test_decide_is_pure_same_disk_same_ledger_same_action(tmp_path, monkeypatch):
    # §6: decide 纯函数性 — same disk + ledger + args -> byte-identical action dict.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    assert schedule.decide("m") == schedule.decide("m")


def test_advisory_edge_never_enters_freshness(tmp_path, monkeypatch):
    # §6/A1-①: sort predicate stays out of validity paths. power←timing is ADVISORY
    # (not an input edge): a fresh power fail must enter disposition even while the
    # timing proof is invalid.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_power("m")  # helper: power's ARTIFACT closure all valid
    _invalidate_proof("m", "timing-analysis")  # helper: drift a timing-only input
    _power_fail("m", run=1)  # fresh power fail (its own inputs untouched)
    hit = schedule._latest_fail(facts.read_events("m"), "power-analysis")
    assert schedule._fail_is_fresh(
        "m", facts.read_events("m"), "power-analysis", hit[0], hit[1]
    )


def test_two_hop_upstream_invalidity_makes_failure_stale(tmp_path, monkeypatch):
    # A1-② livelock regression: timing fail; rtl-design proof (TWO hops up via
    # synthesis) invalid while synthesis proof still valid (RTL bytes unchanged) ->
    # the fail is STALE (transitive closure), so step 1 must NOT re-fire disposition.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _valid("m", "synthesis", 1)
    _reopen("m", "semantic-review")  # rtl-design invalid; RTL bytes unchanged
    _fail("m", "timing-analysis", 1)
    evs = facts.read_events("m")
    hit = schedule._latest_fail(evs, "timing-analysis")
    assert not schedule._fail_is_fresh("m", evs, "timing-analysis", hit[0], hit[1])


def test_repair_rebuild_chain_dispatches_producer_first(tmp_path, monkeypatch):
    # A2 regression / §3.3 末句: repair on timing while the synthesis proof is invalid
    # -> decide(objective="repair") returns DISPATCH synthesis (not ESCALATE).
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _valid("m", "synthesis", 1)
    _reopen("m", "dc-shell")  # synthesis proof invalid, inputs still valid
    _fail("m", "timing-analysis", 1)
    a = schedule.decide("m", objective="repair")
    assert a["action"] == "DISPATCH" and a["rule"] == "synthesis"


def test_human_supersede_restores_auto_rebuild(tmp_path, monkeypatch):
    # §6: an unreliable (low-confidence) triage diagnosis escalates; after `diagnose
    # source=human` supersedes it, decide auto-rebuilds the human-named fix_owner.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", 1)
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "confidence": "low",
            "source": "triage",
        },
        TS,
    )
    assert schedule.decide("m")["action"] == "ESCALATE"  # low confidence -> 叫人
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d2",
            "supersedes": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "evidence": ["human"],
            "source": "human",
            "provenance": "operator",
        },
        TS,
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    assert a["diagnosis_refs"] == ["d2"] and a["triage_forward"] is False


def test_new_outcome_deactivates_old_diagnosis(tmp_path, monkeypatch):
    # §6: subject outcome 被取代后旧归因失活 — after the failed rule re-runs (new fail
    # outcome run N+1), the run-N diagnosis no longer drives disposition: decide
    # dispatches triage anew instead of auto-rebuilding on the stale attribution.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", 1)
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "confidence": "high",
            "source": "triage",
        },
        TS,
    )
    _sim_fail("m", 2)  # simulation re-runs, NEW fail outcome
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "simulation-triage"


def test_triage_blocked_redispatches_no_livelock(tmp_path, monkeypatch):
    # §6: triage blocked (没查出结果) -> the sim failure is still ambiguous with no
    # ready attribution -> next decide re-dispatches simulation-triage (a fresh run
    # number), never YIELD-forever, never ESCALATE.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", 1)
    facts.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "simulation-triage",
            "run": 1,
            "workdir": "Verification/simulation-triage/runs/1",
            "params": {"sim_run": 1},
            "objective": "delivery",
        },
        TS,
    )
    _outcome("m", "simulation-triage", 1, "blocked", {}, [], reason="missing")
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "simulation-triage"


# --- Elided prefix-builder helpers (mechanical, test_facts_freshness pattern) ---
# Each _valid(rule) dispatches+passes a rule with its declared (non-self) inputs on
# disk and matching fingerprints recorded, and its declared outputs written+recorded,
# so facts.proof_valid / facts.rule_available both hold. Content is tagged by run so a
# rebuild at a new run genuinely drifts the produced bytes.

_OUTPUTS = {
    "specification": [
        "Design/specification/design.md",
        "Design/specification/child.md",
        "Design/specification/manifest.json",
        "Design/specification/ppa.json",
        "Design/specification/clocks.json",
        "Design/specification/features.json",
        "Design/specification/timing-scenarios.json",
        "Design/specification/check-hints/c.json",
        "Design/specification/top-io.json",
        "Design/specification/interconnects.json",
        "Design/specification/constraints/top.sdc",
        "Design/specification/constraints/top.sgdc",
    ],
    "simulation-plan": [
        "Verification/simulation-plan/verification-plan.md",
        "Verification/simulation-plan/scaffold-specification.json",
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
        "Design/timing-analysis/timing-actual.json",
    ],
    "simulation": [
        "Verification/simulation/case-results-summary.md",
        "Verification/simulation/env.sh",
        "Verification/simulation/rtl_filelist.f",
        "Verification/simulation/tb/uvm/agent.sv",
    ],
    "power-analysis": ["Verification/power-analysis/reports_ptpx/run1/power_hier.rpt"],
}

# Grades that pin every proposed oracle to human — needed for a passing signoff gate.
_PIN_ALL = {r: "human" for r in rules.FORWARD_PRIORITY}


def _fp(module, rel):
    return facts.fingerprint(facts.module_root(module) / rel)


def _mk(module, rel, content):
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _recorded_inputs(module, rule, extra=()):
    """Current disk fingerprints of `rule`'s declared, non-self input globs + extras.
    Self-produced (in∩out) globs are skipped — proof_valid does not require them and
    they would need same-run output bookkeeping."""
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


def _valid(
    module,
    rule,
    run,
    *,
    oracle_grade=None,
    objective="delivery",
    extra_inputs=(),
    tag=None,
):
    """Dispatch+pass `rule`: write its outputs, record inputs/outputs at current-disk
    fingerprints, emit a passing same-name proof carrying the rule's declared oracle
    (grade optionally overridden)."""
    r = rules.RULES[rule]
    marker = tag if tag is not None else f"r{run}"
    for rel in _OUTPUTS[rule]:
        _mk(module, rel, f"{rule}:{rel}:{marker}")
    inputs = _recorded_inputs(module, rule, extra_inputs)
    outputs = {rel: _fp(module, rel) for rel in _OUTPUTS[rule]}
    grade = oracle_grade or r.oracle[1]
    _dispatch(module, rule, run, inputs, objective=objective)
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
                "oracle": {"ref": r.oracle[0], "grade": grade},
            }
        ],
    )
    # A "human" grade on a proposed oracle is now earned by a REAL live pin, not a recorded
    # snapshot: the signoff gate reads the live grade (facts.oracle_grade), so a post-reap pin
    # takes effect without a re-reap.
    if oracle_grade == "human" and r.oracle[1] == "proposed":
        _pin(module, rule)


def _pin(module, rule):
    """Materialise the oracle-selector content + emit a real live pin whose fingerprint
    matches, so facts.oracle_grade grades the proposed oracle human."""
    r = rules.RULES[rule]
    sel = r.oracle_selector
    rel = sel.replace("*", "oracle_stub.sv") if "*" in sel else sel
    _mk(module, "/".join((*rules.workdir_root(rule), rel)), f"oracle:{rule}")
    facts.append_event(
        module,
        {
            "type": "pin",
            "oracle_ref": r.oracle[0],
            "content_fingerprint": facts.oracle_content_fp(module, r),
            "provenance": "test",
            "reason": "test signoff pin",
        },
        TS,
    )


def _fail(module, rule, run):
    """Dispatch+fail `rule`, recording current-disk inputs and no outputs (so the fail
    is fresh-except-verdict when its input closure is valid)."""
    r = rules.RULES[rule]
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


def _sim_fail(module, run):
    _fail(module, "simulation", run)


def _power_fail(module, run):
    _fail(module, "power-analysis", run)


def _reopen(module, pin_ref):
    facts.append_event(
        module, {"type": "reopen", "pin_ref": pin_ref, "reason": "revoke"}, TS
    )


def _valid_chain_through_simulation(module):
    """spec/plan/rtl proofs valid on disk — simulation's whole input closure."""
    _mk(module, "brainstorm.md", "b1")
    _valid(module, "specification", 1)
    _valid(module, "simulation-plan", 1)
    _valid(module, "rtl-design", 1)


def _valid_chain_through_power(module):
    """power's ARTIFACT closure (spec/plan/rtl/synthesis/simulation) valid — NOT timing,
    which reaches power only through the ADVISORY edge."""
    _mk(module, "brainstorm.md", "b1")
    _valid(module, "specification", 1)
    _valid(module, "simulation-plan", 1)
    _valid(module, "rtl-design", 1)
    _valid(module, "synthesis", 1)
    _valid(module, "simulation", 1)


def _invalidate_proof(module, rule):
    """Build `rule` valid with a rule-private recorded input, then drift that input so
    ONLY this proof goes invalid — its input closure (shared artifacts) is untouched."""
    priv = "/".join(rules.workdir_root(rule)) + "/_private_in.txt"
    _mk(module, priv, "priv-v1")
    _valid(module, rule, 1, extra_inputs=(priv,))
    _mk(module, priv, "priv-v2-drift")


def _build_all_valid(module, run, *, include=None, oracle_grades=None):
    """Dispatch+pass every rule in `include` (default all 8), FORWARD order so each
    rule's upstream outputs already exist on disk when its inputs are recorded."""
    _mk(module, "brainstorm.md", "b1")
    include = include if include is not None else rules.FORWARD_PRIORITY
    grades = oracle_grades or {}
    for rule in rules.FORWARD_PRIORITY:
        if rule not in include:
            continue
        _valid(module, rule, run, oracle_grade=grades.get(rule), objective="delivery")


def test_required_proofs_repair_only_targets_stage_proofs(tmp_path, monkeypatch):
    # F3: repair targets a failed PROOF; simulation-triage produces none. Even if a triage
    # outcome ever carries verdict=fail, required_proofs(repair) must stay within the 8
    # stage proofs — else step-2's sorted(work, key=FORWARD_PRIORITY.index) raises ValueError.
    monkeypatch.chdir(tmp_path)
    _outcome(
        "m", "simulation-triage", 1, "fail", {}, []
    )  # non-proof rule, newest outcome
    req = schedule.required_proofs(facts.read_events("m"), "repair")
    assert "simulation-triage" not in req
    assert req <= set(rules.FORWARD_PRIORITY)


def test_decide_repair_survives_triage_fail_outcome(tmp_path, monkeypatch):
    # F3 symptom: with the whole delivery chain valid and a (buggy) newest triage fail
    # outcome, decide(repair) must not crash — before the fix, required_proofs returns
    # {"simulation-triage"} and step 2 hits FORWARD_PRIORITY.index("simulation-triage").
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _outcome("m", "simulation-triage", 1, "fail", {}, [])
    a = schedule.decide("m", objective="repair")  # must not raise ValueError
    assert a["action"] in ("DONE", "YIELD", "DISPATCH", "ESCALATE")
    assert a.get("rule") != "simulation-triage"


def test_unregistered_rule_in_flight_is_not_reapable_forever(tmp_path, monkeypatch):
    # An in-flight dispatch naming a rule the registry does not know is unreapable —
    # `reap --rule` argparse-rejects it — so surfacing it would wedge the module behind a
    # `REAP` decide keeps returning and no one can execute. in_flight drops it instead.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _dispatch("m", "not-a-rule", 1, {}, objective="delivery")  # never reaped
    assert facts.in_flight(facts.read_events("m")) == []
    assert schedule.decide("m", objective="delivery")["action"] == "DONE"


def test_fresh_fail_fix_owner_in_flight_yields(tmp_path, monkeypatch):
    # E5 / §6 in-flight public premise: when the disposition's fix_owner is already in flight,
    # decide YIELDs — never a double-dispatch.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "evidence": ["x"],
            "confidence": "high",
            "source": "triage",
        },
        TS,
    )
    _dispatch("m", "rtl-design", 2, {})  # fix_owner already in flight
    assert schedule.decide("m", objective="repair")["action"] == "YIELD"


def test_sim_fail_triage_in_flight_yields(tmp_path, monkeypatch):
    # E5 / §6: ambiguous sim failure with simulation-triage already in flight -> YIELD, not a
    # second triage dispatch.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    _dispatch("m", "simulation-triage", 1, {"sim_run": 1})
    assert schedule.decide("m", objective="repair")["action"] == "YIELD"


def test_option_c_defers_producer_with_inflight_consumer(tmp_path, monkeypatch):
    # step-2 forward path: rtl-design has a fresh-but-invalid proof, lint-cdc in-flight.
    # rtl-design's own fail is made STALE (oracle reopened after) so step 1 does not
    # grab it first -> the guard under test is step 2's candidate filter.
    monkeypatch.chdir(tmp_path)
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "rtl-design", 2)
    _reopen("m", "semantic-review")  # stale-ifies the fail (cond 3) -> step 1 skips it
    _dispatch("m", "lint-cdc", 1, {})  # in-flight consumer of Design/rtl-design/*.v
    d = schedule.decide("m", objective="repair")
    assert not (d["action"] == "DISPATCH" and d["rule"] == "rtl-design")
    assert d["action"] in ("YIELD", "DISPATCH")  # YIELD, or a different safe candidate


def test_option_c_defers_fix_owner_rebuild_step1(tmp_path, monkeypatch):
    # step-1 disposition path (spec §4 typical torn-read): a fresh sim failure attributed to
    # rtl-design would DISPATCH the rtl rebuild via _disposition, but lint-cdc (a consumer of
    # rtl-design) is in-flight -> must YIELD, not rebuild rtl under the background read.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "confidence": "high",
            "source": "triage",
        },
        TS,
    )
    _dispatch(
        "m", "lint-cdc", 1, {}
    )  # in-flight consumer of rtl-design, NOT the fix_owner
    d = schedule.decide("m", objective="repair")
    assert not (d["action"] == "DISPATCH" and d["rule"] == "rtl-design")
    assert d["action"] == "YIELD"


def test_signed_off_regresses_on_hand_edit(tmp_path, monkeypatch):
    # E3: the reopen-named freshness test's fixture (empty outputs) structurally cannot
    # exercise a hand-edit. Build a real signed-off chain (on-disk artifacts) and hand-edit
    # one -> its proof invalidates (cond 4) -> signed_off drops. This is the second conjunct
    # of the predicate: the signoff event stays, but a signoff is only as good as the proofs
    # beneath it.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1, oracle_grades=_PIN_ALL)
    facts.append_event(
        "m",
        {"type": "signoff", "provenance": "u", "reason": "ship it"},
        "2026-01-01T00:00:00Z",
    )
    assert facts.signed_off("m", facts.read_events("m")) is True
    _mk(
        "m", "Design/specification/design.md", "HAND-EDITED"
    )  # tamper a promoted artifact
    assert facts.signed_off("m", facts.read_events("m")) is False


def test_signed_off_requires_the_human_act(tmp_path, monkeypatch):
    # First conjunct: every proof valid and every oracle pinned is NOT signed off. Pins are
    # per-oracle judgments made for delivery's sake; the module-level "ship it" is a separate
    # act, and without it nothing may claim signoff.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1, oracle_grades=_PIN_ALL)
    assert facts.signoff_gate("m", facts.read_events("m")) is None  # gate is clear...
    assert (
        facts.signed_off("m", facts.read_events("m")) is False
    )  # ...but nobody signed


def test_signoff_gate_blocks_on_out_of_band_added_input(tmp_path, monkeypatch):
    # a file added out-of-band that matches a rule's input selector (but was not in
    # the recorded inputs) escapes proof_valid conditions 2/4 (which only check recorded
    # paths). The signoff gate rejects it so a smuggled-in source can't ship unverified —
    # enforced ONLY at the signoff trust boundary (daily path keeps the cheap check).
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1, oracle_grades=_PIN_ALL)
    assert facts.signoff_gate("m", facts.read_events("m")) is None  # clean, gate passes
    # a new .v appears in rtl-design/ out-of-band — matches lint/synth/sim `*.v` selectors
    _mk("m", "Design/rtl-design/sneaky.v", "module sneaky; endmodule")
    gate = facts.signoff_gate("m", facts.read_events("m"))
    assert gate is not None
    assert "new input" in gate.lower() and "sneaky.v" in gate


# ── §F: the fail path shares the pass path's condition 3 ──────────────────────
# _fail_is_fresh used to reimplement conditions 2/3/4 and had drifted in two opposite
# directions: anchored on the outcome instead of the dispatch (too loose) and missing the
# live-pin conjunct (too tight). These pin the three scenarios that separate the two.


def _pin_oracle(module, ref, fp="sha256:x", reason="endorse"):
    facts.append_event(
        module,
        {
            "type": "pin",
            "oracle_ref": ref,
            "content_fingerprint": fp,
            "provenance": "p",
            "reason": reason,
        },
        TS,
    )


def _reopen_oracle(module, ref):
    facts.append_event(
        module, {"type": "reopen", "pin_ref": ref, "reason": "revoke"}, TS
    )


def _spec_fail_proof(module):
    root = facts.module_root(module)
    return [
        {
            "name": "specification",
            "verdict": "fail",
            "inputs": {"brainstorm.md": facts.fingerprint(root / "brainstorm.md")},
            "oracle": {"ref": "spec-review", "grade": "proposed"},
        }
    ]


def test_fail_stale_when_reopen_lands_during_the_run(tmp_path, monkeypatch):
    # S1: the oracle is reopened between dispatch and outcome, so the verdict this run
    # produced was judged by an oracle nobody stands behind by the time it lands.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _pin_oracle("m", "spec-review")
    _dispatch("m", "specification", 1, {"brainstorm.md": "sha256:ignored"})
    _reopen_oracle("m", "spec-review")
    _outcome("m", "specification", 1, "fail", {}, _spec_fail_proof("m"))
    events = facts.read_events("m")
    idx, outcome = facts._proof_outcome(events, "specification")
    assert not schedule._fail_is_fresh("m", events, "specification", idx, outcome)


def test_fail_stays_stale_after_a_bare_re_reap(tmp_path, monkeypatch):
    # S2: F5 on the fail path. A re-reap appends a later outcome for the SAME run — it
    # re-executes nothing and re-pins nothing, so it must not launder the fail into a fresh
    # one. Anchoring condition 3 on the dispatch is what makes the second outcome irrelevant.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _pin_oracle("m", "spec-review")
    _dispatch("m", "specification", 1, {"brainstorm.md": "sha256:ignored"})
    _outcome("m", "specification", 1, "fail", {}, _spec_fail_proof("m"))
    _reopen_oracle("m", "spec-review")
    _outcome("m", "specification", 1, "fail", {}, _spec_fail_proof("m"))  # bare re-reap
    events = facts.read_events("m")
    idx, outcome = facts._proof_outcome(events, "specification")
    assert not schedule._fail_is_fresh("m", events, "specification", idx, outcome)


def test_fail_fresh_again_after_a_re_pin(tmp_path, monkeypatch):
    # S3: the other direction. A human re-endorses the oracle after reopening it; the fail
    # verdict is trustworthy again, so the repair path must come back rather than the fail
    # being written off as stale.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _pin_oracle("m", "spec-review")
    _dispatch("m", "specification", 1, {"brainstorm.md": "sha256:ignored"})
    _outcome("m", "specification", 1, "fail", {}, _spec_fail_proof("m"))
    _reopen_oracle("m", "spec-review")  # AFTER the outcome, so the old anchor saw it
    _pin_oracle("m", "spec-review", fp="sha256:y", reason="re-endorse")
    events = facts.read_events("m")
    idx, outcome = facts._proof_outcome(events, "specification")
    assert schedule._fail_is_fresh("m", events, "specification", idx, outcome)


def test_re_reap_does_not_dispatch_upstream_rework(tmp_path, monkeypatch):
    # The harm S2 causes once the failed rule routes somewhere. simulation-plan's failures
    # route to specification, so laundering a stale fail into a fresh one sent a directive-
    # carrying rework at the upstream design doc — on the authority of a simulation-plan
    # verdict whose judge had just been reopened. Stale re-verifies simulation-plan itself.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    root = facts.module_root("m")
    plan_proof = [
        {
            "name": "simulation-plan",
            "verdict": "fail",
            "inputs": {
                "Design/specification/design.md": facts.fingerprint(
                    root / "Design/specification/design.md"
                )
            },
            "oracle": {"ref": "plan-review", "grade": "proposed"},
        }
    ]
    _pin_oracle("m", "plan-review")
    _dispatch("m", "simulation-plan", 2, {"Design/specification/design.md": "sha256:i"})
    _outcome("m", "simulation-plan", 2, "fail", {}, plan_proof)
    _reopen_oracle("m", "plan-review")
    _outcome("m", "simulation-plan", 2, "fail", {}, plan_proof)  # bare re-reap
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH"
    assert a["rule"] == "simulation-plan", (
        f"a stale fail must re-verify its own rule, not rework upstream; got {a['rule']}"
    )
