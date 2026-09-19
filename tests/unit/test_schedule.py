import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import kernel  # noqa: E402
import rules  # noqa: E402
import schedule  # noqa: E402
import store  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def _write(module, rel, text):
    p = store.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return facts.fingerprint(p)


def _workdir(rule, run):
    """The workdir the kernel would record — `Design/specification/runs/1`, not a made-up
    `specification/runs/1`. Everything reached through facts.run_workdir (the no-wake
    ready scan, cmd_reap's workdir) resolves against this, so a fictitious layout
    makes those branches vacuous rather than tested. A rule outside the registry has no
    workdir_root; it only ever appears in the unregistered-in-flight test, which never
    resolves the path."""
    root = rules.RULES[rule].workdir_root if rule in rules.RULES else (rule,)
    return "/".join(root) + f"/runs/{run}"


def _dispatch(module, rule, run, inputs):
    store.append_event(
        module,
        {
            "type": "dispatch",
            "rule": rule,
            "run": run,
            "workdir": _workdir(rule, run),
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
    store.append_event(module, ev, TS)


def _turn(module, limit=6):
    """The rules one Orchestrator turn opens, in order: decide -> dispatch -> decide, never
    reaping, stopping at the first non-DISPATCH. A round can now open several runs, so a test
    about WHICH rule a repair reaches has to look at the turn rather than at decide's first
    answer — a cheap `task` sorting ahead of it does not mean the repair was skipped."""
    out = []
    for run in range(1, limit + 1):
        a = schedule.decide(module)
        if a["action"] != "DISPATCH":
            break
        out.append(a["rule"])
        _dispatch(module, a["rule"], 90 + run, {})
    return out


def test_cold_start_dispatches_specification(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "intent/brainstorm.md", "b1")
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "specification"
    assert a["execution"] == "main-thread"


def test_missing_intent_document_escalates_by_name(tmp_path, monkeypatch):
    # The one unavailability nothing in the pipeline can resolve, and the one `status` cannot
    # show: a module with no intent document renders exactly like one ready to start (every
    # stage `missing`), so the escalation is where a human learns which file to put there.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m").mkdir()
    bare = schedule.decide("m")
    (tmp_path / "m" / "intent" / "refs").mkdir(
        parents=True
    )  # delivery, no entry document
    doc_missing = schedule.decide("m")
    for a in (bare, doc_missing):
        assert a["action"] == "ESCALATE"
        assert rules.INTENT_DOC in a["reason"], a
    _write("m", "intent/brainstorm.md", "b1")
    assert schedule.decide("m")["action"] == "DISPATCH"


def test_wake_reap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "intent/brainstorm.md", "b1")
    _dispatch(
        "m",
        "specification",
        1,
        {"intent": facts.fingerprint(store.module_root("m") / "intent")},
    )
    # workdir result.json present -> REAP even without wake (收口 branch)
    _mk("m", _workdir("specification", 1) + "/result.json", "{}")
    a = schedule.decide("m")
    assert a["action"] == "REAP" and a["rule"] == "specification" and a["run"] == 1
    # --wake names the same run the ready scan would have found on its own; the flag earns
    # its keep only on the branch below, where there is no result.json to scan for.
    assert schedule.decide("m", wake="specification:1") == a


def test_wake_reaps_a_run_whose_executor_wrote_nothing(tmp_path, monkeypatch):
    """The one thing --wake does that the ready scan cannot: a dead executor left no
    result.json, so the scan sees nothing and the ledger would YIELD forever. reap then
    derives blocked and the next decide re-routes."""
    monkeypatch.chdir(tmp_path)
    _write("m", "intent/brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"intent": _fp("m", "intent")})
    assert schedule.decide("m")["action"] == "YIELD"
    a = schedule.decide("m", wake="specification:1")
    assert a["action"] == "REAP" and a["rule"] == "specification" and a["run"] == 1


def test_a_landed_result_is_reaped_not_yielded_over(tmp_path, monkeypatch):
    """Step 0 claims any in-flight run whose workdir holds a result.json, so a YIELD can only
    ever list runs that have not written one. That is why `in_flight[]` carries coordinates
    and nothing else: a per-run "did it finish" flag would be constant false everywhere the
    Orchestrator can see it, and reads as a filter while filtering nothing."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _dispatch("m", "lint-cdc", 1, _recorded_inputs("m", "lint-cdc"))
    _dispatch("m", "simulation-plan", 1, _recorded_inputs("m", "simulation-plan"))
    rj = store.module_root("m") / _workdir("simulation-plan", 1) / "result.json"
    _mk("m", _workdir("simulation-plan", 1) + "/result.json", "{}")
    assert schedule.decide("m") == {
        "action": "REAP",
        "rule": "simulation-plan",
        "run": 1,
    }
    # take the envelope away and the same two runs YIELD instead — carrying coordinates and
    # nothing else, because "has it finished" is exactly what the branch above already used up.
    rj.unlink()
    assert schedule.decide("m") == {
        "action": "YIELD",
        "in_flight": [
            {"rule": "lint-cdc", "run": 1},
            {"rule": "simulation-plan", "run": 1},
        ],
    }


def test_in_flight_no_result_yields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "intent/brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"intent": "sha256:x"})
    a = schedule.decide("m")
    assert a["action"] == "YIELD"
    assert a["in_flight"] == [{"rule": "specification", "run": 1}]


def test_fresh_failure_with_routable_triage_dispatches_fix_owner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # simulation fails fresh; a triage diagnosis points at rtl-design.
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    store.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "source": "triage",
        },
        TS,
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    # The triage analysis reaches the fix owner as the per-run envelope named in
    # caused_by, not as a copied hint: coordinates in, kernel resolves them to paths.
    assert a["caused_by"] == [["simulation", 1]]
    assert a["diagnosis_refs"] == ["d1"]


def _diagnosis(module, did, run, owner):
    store.append_event(
        module,
        {
            "type": "diagnosis",
            "id": did,
            "subject": {"proof": "simulation", "outcome_run": run},
            "attribution": owner,
            "fix_owner": owner,
            "source": "triage",
        },
        TS,
    )


def test_one_failure_with_two_root_causes_reaches_both_owners(tmp_path, monkeypatch):
    """One regression, two independent root causes, two stages that must move. Each owner is
    dispatched, each is told about the same failing run, and each cites only the analysis
    that named it — so the RTL edit and the plan rewrite both get scheduled.

    A real analysis of exactly this shape named one owner while its loci reached into
    another's files; the operator dispatched the second by hand, and a scheduler following
    one name would simply never have scheduled that fix."""
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    _diagnosis("m", "d-rtl", 1, "rtl-design")
    _diagnosis("m", "d-plan", 1, "simulation-plan")

    opened, runs = {}, {}
    for i in range(4):
        a = schedule.decide("m")
        if a["action"] != "DISPATCH":
            break
        opened[a["rule"]] = a
        runs[a["rule"]] = 90 + i
        _dispatch("m", a["rule"], 90 + i, {})
    assert set(opened) == {"rtl-design", "simulation-plan"}
    for rule, ref in (("rtl-design", "d-rtl"), ("simulation-plan", "d-plan")):
        assert opened[rule]["caused_by"] == [["simulation", 1]]
        assert opened[rule]["diagnosis_refs"] == [ref]

    # and the failure stays open until BOTH have had their turn — one owner answering is not
    # the failure answered
    ev = store.read_events("m")
    still = schedule.owed(ev, schedule._failures("m", ev))
    assert still == []
    # that round died, so it re-opens — for its owner alone, not for the other one
    _outcome("m", "rtl-design", runs["rtl-design"], "blocked", {}, [])
    ev = store.read_events("m")
    assert [o["owner"] for o in schedule.owed(ev, schedule._failures("m", ev))] == [
        "rtl-design"
    ]


def test_local_repair_waits_for_its_upstream_repair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    _diagnosis("m", "d-local", 1, "simulation")
    _diagnosis("m", "d-rtl", 1, "rtl-design")
    action = schedule.decide("m")
    assert action["action"] == "DISPATCH" and action["rule"] == "rtl-design"
    _valid("m", "rtl-design", 2)
    action = schedule.decide("m")
    # Independent lint may start first; no upstream repair remains before simulation.
    if action["rule"] == "lint-cdc":
        _dispatch("m", "lint-cdc", 1, {})
        action = schedule.decide("m")
    assert action["action"] == "DISPATCH" and action["rule"] == "simulation"
    assert action["diagnosis_refs"] == ["d-local"]


def test_an_unsure_second_opinion_makes_the_whole_failure_unclear(
    tmp_path, monkeypatch
):
    """Splitting an analysis does not let a confident half carry an unsure one. Part of this
    failure has no owner, and scheduling around a half-known attribution is what the early
    exit exists to prevent — so the round stops on the unsure one and names it."""
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    _diagnosis("m", "d-rtl", 1, "rtl-design")
    store.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d-unsure",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "simulation",  # self-pointing: nothing to route to
            "source": "triage",
        },
        TS,
    )
    a = schedule.decide("m")
    assert a["action"] == "ESCALATE"
    # Both are named: the routable half is held with the unsure one rather than dispatched,
    # and the human it is held for is the only one who will see it — the orchestrator carries
    # nothing between turns, so what decide does not return is not read anywhere else.
    assert [c["diagnosis"] for c in a["candidates"]] == ["d-rtl", "d-unsure"]
    assert [c.get("fix_owner") for c in a["candidates"]] == ["rtl-design", None]


def test_dispatch_args_carry_every_channel_the_action_names(tmp_path, monkeypatch):
    """The action's argv IS the dispatch, so no field can be lost re-serialising it by hand.
    Two co-failing rules routed to one owner: both must appear as --caused-by, both
    diagnoses as --diagnosis-refs."""
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _valid("m", "synthesis", 1)
    _sim_fail("m", 1)
    _fail("m", "timing-analysis", 1)
    for i, (proof, run) in enumerate((("simulation", 1), ("timing-analysis", 1))):
        store.append_event(
            "m",
            {
                "type": "diagnosis",
                "id": f"d{i}",
                "subject": {"proof": proof, "outcome_run": run},
                "attribution": "rtl-design",
                "fix_owner": "rtl-design",
                "source": "triage",
            },
            TS,
        )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    assert a["dispatch_args"] == [
        "dispatch",
        "--module",
        "m",
        "--rule",
        "rtl-design",
        "--caused-by",
        "timing-analysis:1",
        "--caused-by",
        "simulation:1",
        "--diagnosis-refs",
        "d1,d0",
    ]


def test_dispatch_args_carry_declared_params(tmp_path, monkeypatch):
    """A triage dispatch's mandatory sim_run reaches the argv as --params JSON; cmd_dispatch
    rejects the dispatch without it, so a hand-built command line that forgot it was the one
    way to mint an unroutable triage."""
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", 3)
    a = schedule.decide("m")
    assert a["rule"] == "simulation-triage"
    assert a["dispatch_args"][-2:] == ["--params", '{"sim_run": 3}']


def test_decision_diagnosis_can_route_a_local_repair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "simulation-plan", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "simulation", 1)
    assert "simulation" not in rules.input_closure("simulation")
    result = kernel.cmd_diagnose(
        "m", "d0", "simulation", 1, "simulation", "simulation", "op", "TB syntax", None
    )
    assert result["ok"]
    action = schedule.decide("m")
    assert action["action"] == "DISPATCH"
    assert action["rule"] == "simulation"
    assert action["caused_by"] == [["simulation", 1]]
    assert action["diagnosis_refs"] == ["d0"]


def test_fresh_failure_self_pointing_escalates(tmp_path, monkeypatch):
    # Regression: an self-attribution without a fix_owner is
    # a 现成归因 with nothing to route to -> ESCALATE citing it as a candidate. NOT
    # re-dispatch triage, NOT auto-rebuild.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")  # helper: spec/plan/rtl proofs valid on disk
    _sim_fail("m", run=1)  # helper: fresh simulation fail outcome
    store.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "simulation",  # own checks — no fix_owner
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
    # Case: fix changes matvec.v -> simulation fail proof stale -> the turn
    # re-verifies simulation, and never rtl-design again.
    #
    # The same edit also staled lint-cdc, which has no artifact edge to the failure and is
    # opened in the same turn — a `task` executor returning immediately, so it costs the
    # re-verify nothing and reports its own violations hours earlier. That is the shape a
    # real run had (lint-cdc and the regression started 10 minutes apart, after the RTL fix
    # landed), so this asserts the turn rather than decide's first answer.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _fail("m", "simulation", 1, owner="rtl-design")  # records the OLD matvec.v version
    _valid(
        "m", "rtl-design", 2, tag="fix"
    )  # the fix lands, so the owner has had its turn
    opened = _turn("m")
    assert "simulation" in opened and "rtl-design" not in opened
    assert opened.index("lint-cdc") < opened.index(
        "simulation"
    )  # async one starts first


def test_blocked_goes_forward_no_escalate(tmp_path, monkeypatch):
    # blocked outcome -> no proof -> step 2 re-dispatches the rule; never step 1, never ESCALATE.
    monkeypatch.chdir(tmp_path)
    _write("m", "intent/brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"intent": _fp("m", "intent")})
    _outcome("m", "specification", 1, "blocked", {}, [], reason="crash")
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "specification"


def test_fresh_selfdescribing_failure_dispatches_the_owner_its_envelope_named(
    tmp_path, monkeypatch
):
    # The self-describing-failure branch reads `fix_owner` out of the failed rule's CANONICAL
    # result.json: the party that read the raw tool output names who must act, and nothing
    # re-derives that from a classification. Naming nobody is the stage saying it cannot tell.
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "lint-cdc", 1, owner=None)  # the envelope names nobody
    # nobody named and no diagnostic declared for this rule -> ESCALATE
    # (proves the branch genuinely reads the file, not a vacuous pass)
    pre = schedule.decide("m")
    assert pre["action"] == "ESCALATE"
    assert pre["reason"] == "lint-cdc: envelope named no fix_owner"
    _mk(
        "m",
        "Design/lint-cdc/result.json",
        json.dumps(
            {
                "stage_specific": {
                    "fix_owner": "rtl-design",
                    "fail_reason": "clock crossing without a synchronizer",
                }
            }
        ),
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    assert a["caused_by"] == [["lint-cdc", 1]]


def test_fresh_failure_naming_itself_dispatches_repair(tmp_path, monkeypatch):
    """A local defect can be repaired without changing upstream artifacts."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "lint-cdc", 1)
    _mk(
        "m",
        "Design/lint-cdc/result.json",
        json.dumps(
            {
                "stage_specific": {
                    "fix_owner": "lint-cdc",
                    "fail_reason": "false positive needs a waiver I already carry",
                }
            }
        ),
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH"
    assert a["rule"] == "lint-cdc"
    assert a["caused_by"] == [["lint-cdc", 1]]


def test_fresh_failure_naming_outside_its_closure_escalates(tmp_path, monkeypatch):
    """The envelope names the owner; the kernel still checks the naming is legal. rules.py's
    derived input closure is the sole authority, so a stage cannot blame something it does
    not consume."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "lint-cdc", 1)
    _mk(
        "m",
        "Design/lint-cdc/result.json",
        json.dumps(
            {
                "stage_specific": {
                    "fix_owner": "power-analysis",  # not in lint-cdc's input closure
                    "fail_reason": "blaming a stage it never consumes",
                }
            }
        ),
    )
    a = schedule.decide("m")
    assert a["action"] == "ESCALATE"
    assert "neither itself nor an input producer" in a["reason"]


def test_fresh_rtldesign_spec_locus_dispatches_specification(tmp_path, monkeypatch):
    # rtl-design's semantic gate finds a spec-rooted intent defect and its envelope says so
    # in fix_owner. The gate's own loci stay in the envelope as the account behind
    # that naming; nothing outside the stage re-derives the target from them.
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _fail("m", "rtl-design", 1, owner=None)  # the envelope names nobody
    # nobody named and no diagnostic declared for this rule -> ESCALATE
    pre = schedule.decide("m")
    assert pre["action"] == "ESCALATE"
    assert pre["reason"] == "rtl-design: envelope named no fix_owner"
    _mk(
        "m",
        "Design/rtl-design/result.json",
        json.dumps(
            {
                "stage_specific": {
                    "fix_owner": "specification",
                    "fail_reason": "c1 review: §2 width cannot hold the value it requires",
                }
            }
        ),
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "specification"
    assert a["caused_by"] == [["rtl-design", 1]]


def _timing_fail_over_stale_synthesis(module):
    """spec/plan/rtl valid; synthesis report changed (proof invalid, RTL
    bytes untouched); timing-analysis a stale fail. The repair runs through synthesis, whose
    advisory predecessor lint-cdc has never run."""
    _write(module, "intent/brainstorm.md", "b1")
    _valid(module, "specification", 1)
    _valid(module, "simulation-plan", 1)
    _valid(module, "rtl-design", 1)
    _valid(module, "synthesis", 1)
    _mk(module, "Design/synthesis/reports/qor.rpt", "changed measurement")
    _fail(module, "timing-analysis", 1, owner="synthesis")


def test_advisory_holds_while_its_predecessor_is_still_running(tmp_path, monkeypatch):
    """An in-flight predecessor IS going to answer, so the bet the advisory edge makes is
    live and synthesis waits. The turn is not idle — the goal set spans the DAG, so other
    stale work starts — but the expensive stage the cheap detector guards does not."""
    monkeypatch.chdir(tmp_path)
    _timing_fail_over_stale_synthesis("m")
    _dispatch("m", "lint-cdc", 1, _recorded_inputs("m", "lint-cdc"))
    assert "synthesis" not in _turn("m")


def test_advisory_releases_once_its_predecessor_has_spoken(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _timing_fail_over_stale_synthesis("m")
    _valid("m", "lint-cdc", 1)  # it ran and passed
    d = schedule.decide("m")
    assert d["action"] == "DISPATCH" and d["rule"] == "synthesis"


def test_advisory_predecessor_is_scheduled_rather_than_waited_on(tmp_path, monkeypatch):
    """The advisory hold is only ever a bet that the predecessor is about to speak, so the
    predecessor has to be schedulable. It is, because the goal set spans the DAG: a stale
    lint-cdc is picked up in the same turn and synthesis follows it. While the goal set
    narrowed to the failing proof this was the deadlock case — nothing would ever run
    lint-cdc, so the gate had to be taught to give up on it."""
    monkeypatch.chdir(tmp_path)
    _timing_fail_over_stale_synthesis("m")
    _valid("m", "lint-cdc", 1)
    _mk("m", "Design/lint-cdc/lint-report.txt", "drift")  # lint-cdc proof now invalid
    ev = store.read_events("m")
    assert not facts.proof_valid("m", ev, "lint-cdc")
    d = schedule.decide("m")
    assert d["action"] == "DISPATCH" and d["rule"] == "lint-cdc"


def test_advisory_orders_two_stages_that_failed_together(tmp_path, monkeypatch):
    """Both ends of an advisory edge failing puts both in the goal set, so the cheap
    detector runs first instead of racing the expensive stage. A gate keyed on a caller-held
    mode took the opposite bet here from the one it takes when nothing is failing."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "simulation-plan", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "lint-cdc", 1, owner="rtl-design")
    _fail("m", "synthesis", 1, owner="rtl-design")
    _valid(
        "m", "rtl-design", 2, tag="fix"
    )  # one fix answers both; the owner has had its turn
    d = schedule.decide("m")
    assert d["action"] == "DISPATCH" and d["rule"] == "lint-cdc"
    _valid("m", "lint-cdc", 2)
    assert schedule.decide("m")["rule"] == "synthesis"


def test_co_failing_rules_reverify_in_parallel(tmp_path, monkeypatch):
    """The real module's shape: lint-cdc and simulation fail seconds apart, one rtl-design
    round answers both, and then both must be re-verifiable at once — they share no artifact
    edge. Returning a single re-verify target left the second one out of the goal set, so it
    waited for the first to finish (1h53m, in the run this is taken from)."""
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _fail("m", "lint-cdc", 1)
    _sim_fail("m", 1)
    for rule in ("Design/lint-cdc", "Verification/simulation"):
        _mk(
            "m",
            f"{rule}/result.json",
            '{"stage_specific": {"fix_owner": "rtl-design"}}',
        )
    fix = schedule.decide("m")  # step 1 merges both failures into ONE fix
    assert fix["rule"] == "rtl-design"
    assert sorted(fix["caused_by"]) == [["lint-cdc", 1], ["simulation", 1]]
    _valid("m", "rtl-design", 2, tag="fix")  # the fix lands; both fails go stale
    first = schedule.decide("m")
    assert first["action"] == "DISPATCH"
    _dispatch("m", first["rule"], 2, _recorded_inputs("m", first["rule"]))
    second = schedule.decide("m")  # the other one, WITHOUT waiting for the first
    assert second["action"] == "DISPATCH"
    assert {first["rule"], second["rule"]} == {"lint-cdc", "simulation"}


def test_goal_widens_once_nothing_is_failing(tmp_path, monkeypatch):
    """The narrowing has no off switch to forget. lint-cdc fails early, gets fixed and
    re-verifies, and the same loop then builds the rest of the DAG — where a caller-held
    mode reported DONE with five proofs still unbuilt."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "lint-cdc", 1)
    _mk(
        "m",
        "Design/lint-cdc/result.json",
        '{"stage_specific": {"fix_owner": "rtl-design"}}',
    )
    seen = []
    for _ in range(12):
        a = schedule.decide("m")
        if a["action"] != "DISPATCH":
            break
        seen.append(a["rule"])
        _valid("m", a["rule"], facts.runs_of(store.read_events("m"), a["rule"]) + 1)
    assert seen[:2] == [
        "rtl-design",
        "lint-cdc",
    ]  # narrowed: the fix, then the re-verify
    assert a["action"] == "DONE"
    ev = store.read_events("m")
    assert all(facts.proof_valid("m", ev, p) for p in rules.FORWARD_PRIORITY)


def test_signoff_all_valid_done(tmp_path, monkeypatch):
    # All eight stage conclusions are current and the delivery can be accepted.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    assert schedule.decide("m", closing=True)["action"] == "DONE"


def test_closing_changes_what_done_means_not_which_proofs(tmp_path, monkeypatch):
    """`--closing` is a terminal predicate, not a scope. The same log and the same required
    proofs give opposite verdicts, and the gate is the whole of the difference — without it
    the flag would be a no-op reporting DONE with the trust boundary never consulted."""
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _mk("m", "Design/specification/unrecorded.md", "not delivered")
    assert schedule.decide("m")["action"] == "DONE"
    assert schedule.decide("m", closing=True)["action"] == "ESCALATE"


# --- scheduler invariants ---


def test_decide_is_pure_same_disk_same_ledger_same_action(tmp_path, monkeypatch):
    # decide 纯函数性 — same disk + ledger + args -> byte-identical action dict.
    monkeypatch.chdir(tmp_path)
    _write("m", "intent/brainstorm.md", "b1")
    assert schedule.decide("m") == schedule.decide("m")


def test_advisory_edge_never_enters_freshness(tmp_path, monkeypatch):
    # The sort predicate stays out of validity paths. power←timing is ADVISORY
    # (not an input edge): a power failure must stay an OPEN complaint even while the
    # timing proof is invalid, because only ADVISORY_ORDER's own consumer may read it.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_power("m")  # helper: power's ARTIFACT closure all valid
    _invalidate_proof("m", "timing-analysis")  # helper: drift a timing-only input
    _fail("m", "power-analysis", 1, owner="simulation")  # its own inputs untouched
    ev = store.read_events("m")
    owed = schedule.owed(ev, schedule._failures("m", ev))
    assert [(f["rule"], f["owner"]) for f in owed] == [("power-analysis", "simulation")]


def test_two_hop_upstream_invalidity_does_not_discard_the_failure(
    tmp_path, monkeypatch
):
    # Livelock regression, restated for v2. timing fails; rtl-design's proof (TWO hops
    # up via synthesis) is invalid while synthesis's is still valid. The old rule called such
    # a failure STALE and dropped it, which threw away its attribution; the open-complaint
    # rule keeps it and instead refuses to re-run the rule that raised it. Either way the
    # round must not spin: this envelope names nobody, so it is a human's call.
    monkeypatch.chdir(tmp_path)
    _write("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _valid("m", "synthesis", 1)
    _mk(
        "m", "Design/rtl-design/semantic-review/review.md", "changed review"
    )  # rtl-design invalid; RTL bytes unchanged
    _fail("m", "timing-analysis", 1, owner=None)
    fails = schedule._failures("m", store.read_events("m"))
    assert [(f["rule"], f["owners"]) for f in fails] == [("timing-analysis", [])]
    a = schedule.decide("m")
    assert a["action"] == "ESCALATE" and "named no fix_owner" in a["reason"]


def test_repair_rebuild_chain_dispatches_producer_first(tmp_path, monkeypatch):
    # Regression: repair on timing while the synthesis proof is invalid
    # -> the round rebuilds the PRODUCER, never ESCALATE. With lint-cdc already valid its
    # advisory edge is satisfied, so synthesis is the first thing the turn opens; the
    # unsatisfied case is test_advisory_predecessor_is_scheduled_rather_than_waited_on.
    monkeypatch.chdir(tmp_path)
    _write("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _valid("m", "lint-cdc", 1)
    _valid("m", "synthesis", 1)
    _mk(
        "m", "Design/synthesis/reports/qor.rpt", "changed measurement"
    )  # synthesis proof invalid, inputs still valid
    _fail("m", "timing-analysis", 1, owner="synthesis")
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "synthesis"


def test_decision_supersede_restores_auto_rebuild(tmp_path, monkeypatch):
    # A triage diagnosis naming nobody schedulable escalates; after `diagnose
    # source=decision` supersedes it, decide auto-rebuilds the human-named fix_owner.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", 1)
    store.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "simulation",  # self-pointing -> no fix_owner
            "source": "triage",
        },
        TS,
    )
    assert schedule.decide("m")["action"] == "ESCALATE"  # 没点出可派的人 -> 叫人
    store.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d2",
            "supersedes": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "source": "decision",
            "provenance": "operator",
        },
        TS,
    )
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "rtl-design"
    assert a["diagnosis_refs"] == ["d2"] and a["caused_by"] == [["simulation", 1]]


def test_new_outcome_deactivates_old_diagnosis(tmp_path, monkeypatch):
    # subject outcome 被取代后旧归因失活 — after the failed rule re-runs (new fail
    # outcome run N+1), the run-N diagnosis no longer drives disposition: decide
    # dispatches triage anew instead of auto-rebuilding on the stale attribution.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", 1)
    store.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "source": "triage",
        },
        TS,
    )
    _sim_fail("m", 2)  # simulation re-runs, NEW fail outcome
    a = schedule.decide("m")
    assert a["action"] == "DISPATCH" and a["rule"] == "simulation-triage"


def test_triage_blocked_redispatches_no_livelock(tmp_path, monkeypatch):
    # triage blocked (没查出结果) -> the sim failure is still ambiguous with no
    # ready attribution -> next decide re-dispatches simulation-triage (a fresh run
    # number), never YIELD-forever, never ESCALATE.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", 1)
    store.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "simulation-triage",
            "run": 1,
            "workdir": "Verification/simulation-triage/runs/1",
            "params": {"sim_run": 1},
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
        "Design/specification/children",
        "Design/specification/manifest.json",
        "Design/specification/requirements.json",
        "Design/specification/clocks.json",
        "Design/specification/check-hints.json",
        "Design/specification/top-io.json",
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
        "Design/rtl-design/src",
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
        # filelist.f is declared by simulation AND consumed by power-analysis's tb_env key.
        # Omitting it made power-analysis permanently unavailable here, so nothing in this
        # file ever forward-dispatched the last stage or reached DONE through step 2.
        "Verification/simulation/filelist.f",
        "Verification/simulation/rtl_filelist.f",
        "Verification/simulation/scripts/run_vcs_regression.sh",
        "Verification/simulation/tb/uvm/agent.sv",
        "Verification/simulation/tests/testlist.json",
    ],
    "power-analysis": ["Verification/power-analysis/reports_ptpx/run1/power_hier.rpt"],
}


def _fp(module, rel):
    return facts.fingerprint(store.module_root(module) / rel)


def _mk(module, rel, content):
    if not Path(rel).suffix:  # tree artifact (Design/rtl-design/src): one file inside
        return _mk(module, rel + "/rtl.v", content)
    p = store.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _recorded_inputs(module, rule, extra=()):
    """Current disk fingerprints of `rule`'s declared, non-self input globs + extras.
    Self-produced (in∩out) globs are skipped — proof_valid does not require them and
    they would need same-run output bookkeeping."""
    root = store.module_root(module)
    rec = {}
    for globs in rules.RULES[rule].inputs.values():
        for g in globs:
            if rules.producer_of(g) == rule:
                continue
            for p in sorted(root.glob(g)):
                rec[str(p.relative_to(root))] = facts.fingerprint(p)
    for rel in extra:
        rec[rel] = _fp(module, rel)
    return rec


def _valid(module, rule, run, *, extra_inputs=(), tag=None):
    """Publish fixture evidence and record its current input/output fingerprints."""
    marker = tag if tag is not None else f"r{run}"
    rels = list(_OUTPUTS[rule])
    reviews = {
        "specification": "spec-review/review.md",
        "simulation-plan": "plan-review/review.md",
        "rtl-design": "semantic-review/review.md",
        "simulation": "tb/uvm/refmodel/ref.sv",
    }
    if rule in reviews:
        rels.append("/".join((*rules.workdir_root(rule), reviews[rule])))
    for rel in rels:
        _mk(module, rel, f"{rule}:{rel}:{marker}")
    inputs = _recorded_inputs(module, rule, extra_inputs)
    outputs = {rel: _fp(module, rel) for rel in rels}
    _dispatch(module, rule, run, inputs)
    _outcome(
        module,
        rule,
        run,
        "pass",
        outputs,
        [{"name": rule, "verdict": "pass", "inputs": inputs}],
    )


def _fail(module, rule, run, owner="auto"):
    """Dispatch+fail `rule`, recording current-disk inputs and no outputs.

    Also writes the canonical envelope naming a fix owner, because every stage contract
    requires one on a failure (`--fix-owner` on every failure) and the scheduler now stops
    the round on a failure nobody attributed. `owner="auto"` picks the first legal target;
    pass `owner=None` for the deliberately-unattributed case."""
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
            }
        ],
    )


def _sim_fail(module, run):
    """simulation read its logs and its reference model and still cannot attribute — the
    case `simulation/SKILL.md` calls "an answer rather than a shrug", and the only one that
    reaches the declared diagnostic."""
    _fail(module, "simulation", run, owner=None)


def _power_fail(module, run):
    _fail(module, "power-analysis", run)


def _valid_chain_through_simulation(module):
    """spec/plan/rtl proofs valid on disk — simulation's whole input closure."""
    _mk(module, "intent/brainstorm.md", "b1")
    _valid(module, "specification", 1)
    _valid(module, "simulation-plan", 1)
    _valid(module, "rtl-design", 1)


def _valid_chain_through_power(module):
    """power's ARTIFACT closure (spec/plan/rtl/synthesis/simulation) valid — NOT timing,
    which reaches power only through the ADVISORY edge."""
    _mk(module, "intent/brainstorm.md", "b1")
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


def _build_all_valid(module, run, *, include=None):
    """Dispatch+pass every rule in `include` (default all 8), FORWARD order so each
    rule's upstream outputs already exist on disk when its inputs are recorded."""
    _mk(module, "intent/brainstorm.md", "b1")
    include = include if include is not None else rules.FORWARD_PRIORITY
    for rule in rules.FORWARD_PRIORITY:
        if rule not in include:
            continue
        _valid(module, rule, run)


def test_decide_repair_survives_triage_fail_outcome(tmp_path, monkeypatch):
    # A diagnostic outcome does not add a stage proof to the work set.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _outcome("m", "simulation-triage", 1, "fail", {}, [])
    a = schedule.decide("m")  # must not raise ValueError
    assert a["action"] == "DONE"
    assert a.get("rule") != "simulation-triage"


def test_unregistered_rule_in_flight_is_not_reapable_forever(tmp_path, monkeypatch):
    # An in-flight dispatch naming a rule the registry does not know is unreapable —
    # `reap --rule` argparse-rejects it — so surfacing it would wedge the module behind a
    # `REAP` decide keeps returning and no one can execute. in_flight drops it instead.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _dispatch("m", "not-a-rule", 1, {})  # never reaped
    assert facts.in_flight(store.read_events("m")) == []
    assert schedule.decide("m")["action"] == "DONE"


def test_fresh_fail_fix_owner_in_flight_yields(tmp_path, monkeypatch):
    # In-flight public premise: when the disposition's fix_owner is already in flight,
    # decide YIELDs — never a double-dispatch.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    store.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "source": "triage",
        },
        TS,
    )
    _dispatch("m", "rtl-design", 2, {})  # fix_owner already in flight
    assert schedule.decide("m")["action"] == "YIELD"


def test_sim_fail_triage_in_flight_is_not_dispatched_twice(tmp_path, monkeypatch):
    # Ambiguous sim failure with simulation-triage already in flight -> no second
    # triage dispatch. The turn is not idle — other stale work starts alongside the analysis.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    _dispatch("m", "simulation-triage", 1, {"sim_run": 1})
    assert "simulation-triage" not in _turn("m")


def test_option_c_defers_producer_with_inflight_consumer(tmp_path, monkeypatch):
    """The torn read: promoting a new rtl-design under lint-cdc's canonical read. Nothing
    has failed here — rtl-design is simply due a rebuild — so the guard under test is the
    candidate filter alone, with no attribution in the picture."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "intent/brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _mk("m", "Design/rtl-design/semantic-review/child.md", "drift")  # rtl proof invalid
    _dispatch("m", "lint-cdc", 1, {})  # in-flight consumer of Design/rtl-design/*.v
    d = schedule.decide("m")
    assert not (d["action"] == "DISPATCH" and d["rule"] == "rtl-design")
    assert d["action"] in ("YIELD", "DISPATCH")  # YIELD, or a different safe candidate


def test_option_c_defers_fix_owner_rebuild_step1(tmp_path, monkeypatch):
    # step-1 disposition path (typical torn-read): a fresh sim failure attributed to
    # rtl-design would DISPATCH the rtl rebuild via _disposition, but lint-cdc (a consumer of
    # rtl-design) is in-flight -> must YIELD, not rebuild rtl under the background read.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    store.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "rtl-design",
            "fix_owner": "rtl-design",
            "source": "triage",
        },
        TS,
    )
    _dispatch(
        "m", "lint-cdc", 1, {}
    )  # in-flight consumer of rtl-design, NOT the fix_owner
    d = schedule.decide("m")
    assert not (d["action"] == "DISPATCH" and d["rule"] == "rtl-design")
    assert d["action"] in ("YIELD", "DISPATCH")  # YIELD, or a different safe candidate


def test_signed_off_regresses_on_hand_edit(tmp_path, monkeypatch):
    # Editing accepted evidence invalidates the acceptance without deleting its event.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    store.append_event(
        "m",
        {"type": "signoff", "provenance": "u", "reason": "ship it"},
        "2026-01-01T00:00:00Z",
    )
    assert facts.signed_off("m", store.read_events("m")) is True
    _mk(
        "m", "Design/specification/design.md", "HAND-EDITED"
    )  # tamper a promoted artifact
    assert facts.signed_off("m", store.read_events("m")) is False


def test_signed_off_requires_the_signoff_decision(tmp_path, monkeypatch):
    # Valid evidence does not itself constitute an acceptance decision.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    assert facts.signoff_gate("m", store.read_events("m")) is None  # gate is clear...
    assert (
        facts.signed_off("m", store.read_events("m")) is False
    )  # ...but nobody signed


def test_signoff_gate_blocks_on_a_file_the_stage_never_delivered(tmp_path, monkeypatch):
    # A new file outside the recorded artifact paths is not covered by their fingerprints.
    # The acceptance gate checks that the whole published delivery is recorded.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    assert facts.signoff_gate("m", store.read_events("m")) is None  # clean, gate passes
    _mk("m", "Design/rtl-design/sneaky.vh", "`define SNEAKY 1")
    gate = facts.signoff_gate("m", store.read_events("m"))
    assert gate is not None
    assert "unrecorded file" in gate and "sneaky.vh" in gate


def test_a_file_added_inside_the_delivered_tree_invalidates_at_once(
    tmp_path, monkeypatch
):
    # Adding a file inside a recorded tree changes its fingerprint immediately.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    assert facts.proof_valid("m", store.read_events("m"), "rtl-design")
    _mk("m", "Design/rtl-design/src/sneaky.vh", "`define SNEAKY 1")
    assert not facts.proof_valid("m", store.read_events("m"), "rtl-design")


# ── the gate says whether; the basis says what ────────────────────────────────
def _all_valid(module):
    _build_all_valid(module, 1)
    assert facts.signoff_gate(module, store.read_events(module)) is None


def test_basis_covers_every_proof_in_forward_order(tmp_path, monkeypatch):
    # A signoff record whose row order varied by hash seed would not be a record.
    monkeypatch.chdir(tmp_path)
    _all_valid("m")
    basis = facts.signoff_basis(store.read_events("m"))
    assert [b["proof"] for b in basis] == list(rules.FORWARD_PRIORITY)


def test_basis_names_the_input_set_each_verdict_was_about(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _all_valid("m")
    events = store.read_events("m")
    by_proof = {b["proof"]: b for b in facts.signoff_basis(events)}
    spec = by_proof["specification"]
    assert spec["inputs"] == ["intent"]
    # and it matches what the proof actually recorded, not a re-derivation from rules.py
    _, outcome = facts.proof_outcome(events, "specification")
    proof = next(p for p in outcome["proofs"] if p["name"] == "specification")
    assert spec["inputs"] == sorted(proof["inputs"])


def test_decide_signoff_done_carries_the_basis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _all_valid("m")
    a = schedule.decide("m", closing=True)
    assert a["action"] == "DONE"
    assert [b["proof"] for b in a["basis"]] == list(rules.FORWARD_PRIORITY)


def test_decide_signoff_escalate_carries_no_basis(tmp_path, monkeypatch):
    # Nothing is being accepted when the gate blocks; a basis there would read as an offer.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _mk("m", "Design/specification/unrecorded.md", "not delivered")
    a = schedule.decide("m", closing=True)
    assert a["action"] == "ESCALATE" and "basis" not in a
