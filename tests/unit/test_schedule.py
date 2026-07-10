import json
import sys
from pathlib import Path

import pytest

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
    assert pre["action"] == "ESCALATE" and pre["reason"] == "lint_no_category"
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
    assert not (d["action"] == "DISPATCH" and d["rule"] == "synthesis")
    r = schedule.decide("m", objective="repair")
    assert r["action"] == "DISPATCH" and r["rule"] == "synthesis"


def test_epoch_conservative_reuse_and_done(tmp_path, monkeypatch):
    # after an epoch, proofs whose outcome predates the anchor are NOT reusable under
    # conservative; those after are. signoff reaches DONE once all rebuilt post-anchor.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)  # all 9 proofs valid, PRE-anchor
    _epoch("m")
    a = schedule.decide("m", objective="signoff")  # forces conservative
    assert a["action"] == "DISPATCH"  # pre-anchor proofs not reusable -> full rebuild
    _build_all_valid("m", 2, oracle_grades=_PIN_ALL)  # rebuilt POST-anchor
    assert schedule.decide("m", objective="signoff")["action"] == "DONE"


def test_signoff_gate_blocks_without_epoch_or_with_proposed(tmp_path, monkeypatch):
    # objective=signoff with no epoch -> SystemExit ("open an epoch first" — spec §3.6
    # 报错不静默兜底, an error not an action); a proposed-grade oracle proof (unpinned)
    # under an open epoch -> ESCALATE "oracle is proposed (pin it)".
    monkeypatch.chdir(tmp_path)
    # (a) no epoch -> hard error, not an action.
    _build_all_valid("noepoch", 1)  # all valid, NO epoch event
    with pytest.raises(SystemExit, match="open an epoch first"):
        schedule.decide("noepoch", objective="signoff")
    # (b) open epoch, 8 upstream valid post-anchor, frontend-signoff the sole candidate
    # that hits the gate; default oracle grades leave several proofs "proposed". The
    # reason must name the FIRST offender in FORWARD_PRIORITY order (specification) —
    # deterministic, never hash-seed-dependent set order.
    _epoch("proposed")
    _build_all_valid("proposed", 1, include=rules.FORWARD_PRIORITY[:8])
    a = schedule.decide("proposed", objective="signoff")
    assert a["action"] == "ESCALATE"
    assert a["reason"] == "signoff blocked: specification oracle is proposed (pin it)"


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


def test_adjacent_epochs_do_not_fuse(tmp_path, monkeypatch):
    # §6: 相邻两纪元不黏连 — after a completed signoff epoch, opening a second epoch
    # makes every proof pre-anchor again: first conservative decide -> DISPATCH (full
    # rebuild), not DONE.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _epoch("m")  # epoch 1
    _build_all_valid(
        "m", 2, oracle_grades=_PIN_ALL
    )  # rebuilt post-epoch-1 (would be DONE)
    _epoch("m")  # epoch 2 -> every proof pre-anchor again
    a = schedule.decide("m", objective="signoff")
    assert a["action"] == "DISPATCH"


def test_epoch_internal_repair_keeps_prefix(tmp_path, monkeypatch):
    # §6: 纪元内修复插曲不作废前缀 — proofs rebuilt post-anchor stay reusable across a
    # failure+fix episode inside the same epoch (no new epoch event in between).
    monkeypatch.chdir(tmp_path)
    _epoch("m")
    _build_all_valid("m", 1)  # prefix built POST-anchor
    _sim_fail("m", 2)  # failure episode, same epoch (no epoch event)
    _valid("m", "rtl-design", 2, tag="fix")  # fix lands, still same epoch
    evs = facts.read_events("m")
    assert schedule._reusable("m", evs, "specification", True)  # prefix survives
    assert schedule._reusable("m", evs, "rtl-design", True)  # the fix is post-anchor


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


def test_conservative_workset_superset_of_regular(tmp_path, monkeypatch):
    # §6 invariant: --conservative 工作集 ⊇ 常规 — a proof valid but PRE-anchor: plain
    # delivery reuses it (DONE), conservative re-dispatches its rule.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1, include=rules.FORWARD_PRIORITY[:8])  # delivery set, valid
    _epoch("m")  # anchor AFTER the proofs -> all pre-anchor
    assert schedule.decide("m")["action"] == "DONE"  # plain delivery reuses
    assert schedule.decide("m", conservative=True)["action"] == "DISPATCH"  # superset


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
        "Design/specification/constraints/top.sdc",
        "Design/specification/constraints/top.sgdc",
    ],
    "simulation-plan": [
        "Verification/simulation-plan/verification-plan.md",
        "Verification/simulation-plan/scaffold-specification.json",
    ],
    "rtl-design": [
        "Design/rtl-design/matvec.v",
        "Design/rtl-design/filelist.txt",
        "Design/rtl-design/README.md",
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
    "frontend-signoff": [
        "frontend-signoff/checklist.md",
        "frontend-signoff/traceability.md",
    ],
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


def _epoch(module):
    facts.append_event(
        module,
        {
            "type": "epoch",
            "objective": "signoff",
            "provenance": "test",
            "reason": "sign off",
        },
        TS,
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
    """Dispatch+pass every rule in `include` (default all 9), FORWARD order so each
    rule's upstream outputs already exist on disk when its inputs are recorded."""
    _mk(module, "brainstorm.md", "b1")
    include = include if include is not None else rules.FORWARD_PRIORITY
    grades = oracle_grades or {}
    for rule in rules.FORWARD_PRIORITY:
        if rule not in include:
            continue
        objective = "signoff" if rule == "frontend-signoff" else "delivery"
        _valid(module, rule, run, oracle_grade=grades.get(rule), objective=objective)
