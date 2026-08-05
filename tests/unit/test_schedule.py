import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import kernel  # noqa: E402
import rules  # noqa: E402
import schedule  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def _write(module, rel, text):
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return facts.fingerprint(p)


def _workdir(rule, run):
    """The workdir the kernel would record — `Design/specification/runs/1`, not a made-up
    `specification/runs/1`. Everything reached through schedule._workdir_of (the no-wake
    ready scan, cmd_reap's workdir) resolves against this, so a fictitious layout
    makes those branches vacuous rather than tested. A rule outside the registry has no
    workdir_root; it only ever appears in the unregistered-in-flight test, which never
    resolves the path."""
    root = rules.RULES[rule].workdir_root if rule in rules.RULES else (rule,)
    return "/".join(root) + f"/runs/{run}"


def _dispatch(module, rule, run, inputs):
    facts.append_event(
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
    facts.append_event(module, ev, TS)


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
    _write("m", "brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"brainstorm.md": _fp("m", "brainstorm.md")})
    assert schedule.decide("m")["action"] == "YIELD"
    a = schedule.decide("m", wake="specification:1")
    assert a["action"] == "REAP" and a["rule"] == "specification" and a["run"] == 1


def test_a_landed_result_is_reaped_not_yielded_over(tmp_path, monkeypatch):
    """Step 0 claims any in-flight run whose workdir holds a result.json, so a YIELD can only
    ever list runs that have not written one. That is why `in_flight[]` carries no "did it
    finish" flag: it would be constant false everywhere the Orchestrator can see it, and
    reads as a filter while filtering nothing. `executor_wrote` is the different question —
    did anything ever START — and that one is not constant (see
    test_yield_says_whether_the_executor_ever_wrote)."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _dispatch("m", "lint-cdc", 1, _recorded_inputs("m", "lint-cdc"))
    _dispatch("m", "simulation-plan", 1, _recorded_inputs("m", "simulation-plan"))
    rj = facts.module_root("m") / _workdir("simulation-plan", 1) / "result.json"
    _mk("m", _workdir("simulation-plan", 1) + "/result.json", "{}")
    assert schedule.decide("m") == {
        "action": "REAP",
        "rule": "simulation-plan",
        "run": 1,
    }
    # take the envelope away and the same two runs YIELD instead — carrying coordinates and
    # nothing else, because "has it finished" is exactly what the branch above already used up.
    rj.unlink()
    a = schedule.decide("m")
    assert a["action"] == "YIELD"
    assert [(f["rule"], f["run"]) for f in a["in_flight"]] == [
        ("lint-cdc", 1),
        ("simulation-plan", 1),
    ]


def test_in_flight_no_result_yields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"brainstorm.md": "sha256:x"})
    a = schedule.decide("m")
    assert a["action"] == "YIELD"
    assert [(f["rule"], f["run"]) for f in a["in_flight"]] == [("specification", 1)]


def test_yield_says_whether_the_executor_ever_wrote(tmp_path, monkeypatch):
    """`dispatch` opening a run does not mean a process is running it. One real run idled
    6h10m because the Orchestrator marked a stage in flight and never launched it, and the
    ledger looked identical to a stage still working. The distinguishing fact is on disk —
    something newer than the dispatch's own `dispatch.json` — so the YIELD carries it."""
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"brainstorm.md": "sha256:x"})
    wd = _workdir("specification", 1)
    _mk("m", wd + "/dispatch.json", "{}")

    a = schedule.decide("m")
    assert a["in_flight"] == [
        {
            "rule": "specification",
            "run": 1,
            "dispatched_at": facts.read_events("m")[0]["ts"],
            "executor_wrote": False,
        }
    ]

    # anything the dispatch did not put there flips it — carried files do not, because
    # store.carry_self copies with copy2 and keeps the source mtime.
    p = facts.module_root("m") / wd / "draft.md"
    p.write_text("working")
    os.utime(p, ns=(0, (facts.module_root("m") / wd / "dispatch.json").stat().st_mtime_ns))
    assert schedule.decide("m")["in_flight"][0]["executor_wrote"] is False
    p.write_text("working, and later than the dispatch")
    assert schedule.decide("m")["in_flight"][0]["executor_wrote"] is True


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
    # The triage analysis reaches the fix owner as the per-run envelope named in
    # caused_by, not as a copied hint: coordinates in, kernel resolves them to paths.
    assert a["caused_by"] == [["simulation", 1]]
    assert a["diagnosis_refs"] == ["d1"]


def _diagnosis(module, did, run, owner, locus):
    facts.append_event(
        module,
        {
            "type": "diagnosis",
            "id": did,
            "subject": {"proof": "simulation", "outcome_run": run},
            "attribution": owner,
            "fix_owner": owner,
            "fix_locus": [locus],
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "confidence": "high",
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
    _diagnosis("m", "d-rtl", 1, "rtl-design", "core_muldiv.v:129")
    _diagnosis("m", "d-plan", 1, "simulation-plan", "verification-plan.md:88")

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
    ev = facts.read_events("m")
    still = schedule.owed(ev, schedule._failures("m", ev))
    assert still == []
    # that round died, so it re-opens — for its owner alone, not for the other one
    _outcome("m", "rtl-design", runs["rtl-design"], "blocked", {}, [])
    ev = facts.read_events("m")
    assert [o["owner"] for o in schedule.owed(ev, schedule._failures("m", ev))] == [
        "rtl-design"
    ]


def test_an_unsure_second_opinion_makes_the_whole_failure_unclear(
    tmp_path, monkeypatch
):
    """Splitting an analysis does not let a confident half carry an unsure one. Part of this
    failure has no owner, and scheduling around a half-known attribution is what the early
    exit exists to prevent — so the round stops on the unsure one and names it."""
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    _diagnosis("m", "d-rtl", 1, "rtl-design", "core_muldiv.v:129")
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d-unsure",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "simulation",  # self-pointing: nothing to route to
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "confidence": "high",
            "source": "triage",
        },
        TS,
    )
    a = schedule.decide("m")
    assert a["action"] == "ESCALATE"
    assert [c["diagnosis"] for c in a["candidates"]] == ["d-unsure"]


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
        facts.append_event(
            "m",
            {
                "type": "diagnosis",
                "id": f"d{i}",
                "subject": {"proof": proof, "outcome_run": run},
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


def test_neither_writer_can_mint_a_routable_self_pointing_diagnosis(
    tmp_path, monkeypatch
):
    """The reliability gate refuses an oracle-side attribution on the `fix_owner` clause
    alone, so it needs no separate attribution test — and could not use one, because neither
    writer can produce a self-pointing diagnosis that carries a `fix_owner`."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "simulation-plan", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "simulation", 1)
    # the human path: cmd_diagnose rejects a fix_owner outside the subject's input closure,
    # and the graph is acyclic, so the subject is never inside its own.
    assert not any(r in rules.input_closure(r) for r in rules.RULES)
    r = kernel.cmd_diagnose(
        "m",
        "d0",
        "simulation",
        1,
        "simulation",
        "simulation",
        None,
        ["e"],
        "op",
        "why",
        None,
    )
    assert not r["ok"] and "not in input closure" in r["error"]
    # the triage path: _derive_triage writes fix_owner only for a root cause inside that
    # same closure, so root_cause == simulation lands recorded but unroutable.
    assert "simulation" not in rules.input_closure("simulation")


def test_fresh_failure_self_pointing_escalates(tmp_path, monkeypatch):
    # A3 regression: an oracle-side attribution (root_cause=simulation, so no fix_owner) is
    # a 现成归因 that is UNRELIABLE -> ESCALATE citing it as a candidate. NOT re-dispatch
    # triage, NOT auto-rebuild. `confidence: high` is present to show it does not rescue a
    # diagnosis with nothing to route to.
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


def test_escalation_names_the_verb_that_clears_it(tmp_path, monkeypatch):
    """An ESCALATE stops the whole round, so it has to say what reopens it. `diagnose` for an
    attribution nobody can act on, superseding the one that failed; `pin` for a retracted
    oracle, because `_owner` checks the retraction ahead of any diagnosis and a fresh one
    would not be consulted."""
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_simulation("m")
    _sim_fail("m", run=1)
    facts.append_event(
        "m",
        {
            "type": "diagnosis",
            "id": "d1",
            "subject": {"proof": "simulation", "outcome_run": 1},
            "attribution": "simulation",
            "evidence": ["Verification/simulation-triage/runs/1/result.json"],
            "confidence": "high",
            "source": "triage",
        },
        TS,
    )
    remedy = schedule.decide("m")["remedy"]
    assert remedy[0] == "diagnose"
    assert remedy[remedy.index("--subject-proof") + 1] == "simulation"
    assert remedy[remedy.index("--subject-run") + 1] == "1"
    assert remedy[remedy.index("--supersedes") + 1] == "d1"
    # the choice it leaves open is bounded by what the kernel would accept
    offered = remedy[remedy.index("--fix-owner") + 1]
    assert set(rules.input_closure("simulation")) == set(
        offered.strip("<>").removeprefix("one of: ").split(", ")
    )

    # and it is not one branch: every class says what unblocks it
    for named in (None, "simulation", "lint-cdc"):  # nobody / itself / outside the closure
        c = {
            "rule": "simulation",
            "run": 2,
            "attribution": named,
            "unreliable": [],
            "retracted": False,
        }
        assert schedule._escalation("m", c)["remedy"][0] == "diagnose"
    retracted = schedule._escalation(
        "m",
        {
            "rule": "simulation",
            "run": 2,
            "attribution": None,
            "unreliable": [],
            "retracted": True,
        },
    )
    assert retracted["remedy"][:2] == ["pin", "--module"]


def test_repair_after_fix_lands_redispatches_failed_rule_not_fix_owner(
    tmp_path, monkeypatch
):
    # spec §3.4 case: fix changes matvec.v -> simulation fail proof stale -> the turn
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
    assert opened.index("lint-cdc") < opened.index("simulation")  # async one starts first


def test_blocked_goes_forward_no_escalate(tmp_path, monkeypatch):
    # blocked outcome -> no proof -> step 2 re-dispatches the rule; never step 1, never ESCALATE.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _dispatch("m", "specification", 1, {"brainstorm.md": _fp("m", "brainstorm.md")})
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
    _mk("m", "brainstorm.md", "b1")
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


def test_fresh_failure_naming_itself_escalates(tmp_path, monkeypatch):
    """A defect the stage could fix from here is fixed WITHIN its run, so it never arrives as
    a failure. Naming itself therefore means the in-stage remedy is exhausted, and an
    auto-rebuild would dispatch the failing rule at itself."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "brainstorm.md", "b1")
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
    assert a["action"] == "ESCALATE"
    assert "fix_owner is itself" in a["reason"]


def test_fresh_failure_naming_outside_its_closure_escalates(tmp_path, monkeypatch):
    """The envelope names the owner; the kernel still checks the naming is legal. rules.py's
    derived input closure is the sole authority, so a stage cannot blame something it does
    not consume."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "brainstorm.md", "b1")
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
    assert "outside its input closure" in a["reason"]


def test_fresh_rtldesign_spec_locus_dispatches_specification(tmp_path, monkeypatch):
    # rtl-design's semantic gate finds a spec-rooted intent defect and its envelope says so
    # in fix_owner. The gate's own loci/confidence stay in the envelope as the account behind
    # that naming; nothing outside the stage re-derives the target from them.
    monkeypatch.chdir(tmp_path)
    _mk("m", "brainstorm.md", "b1")
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
    """spec/plan/rtl valid; synthesis built then its oracle reopened (proof invalid, RTL
    bytes untouched); timing-analysis a stale fail. The repair runs through synthesis, whose
    advisory predecessor lint-cdc has never run."""
    _write(module, "brainstorm.md", "b1")
    _valid(module, "specification", 1)
    _valid(module, "simulation-plan", 1)
    _valid(module, "rtl-design", 1)
    _valid(module, "synthesis", 1)
    _reopen(module, "dc-shell")
    _fail(module, "timing-analysis", 1, owner="synthesis")


def test_advisory_holds_while_its_predecessor_is_still_running(tmp_path, monkeypatch):
    """An in-flight predecessor IS going to answer, so the bet the advisory edge makes is
    live and synthesis waits. The turn is not idle — the goal set spans the DAG, so other
    stale work starts — but the expensive stage the cheap detector guards does not."""
    monkeypatch.chdir(tmp_path)
    _timing_fail_over_stale_synthesis("m")
    _dispatch("m", "lint-cdc", 1, _recorded_inputs("m", "lint-cdc"))
    assert schedule.failing_proofs(facts.read_events("m")) == {"timing-analysis"}
    assert "synthesis" not in _turn("m")


def test_advisory_releases_once_its_predecessor_has_spoken(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _timing_fail_over_stale_synthesis("m")
    _valid("m", "lint-cdc", 1)  # it ran and passed
    d = schedule.decide("m")
    assert d["action"] == "DISPATCH" and d["rule"] == "synthesis"


def test_advisory_predecessor_is_scheduled_rather_than_waited_on(
    tmp_path, monkeypatch
):
    """The advisory hold is only ever a bet that the predecessor is about to speak, so the
    predecessor has to be schedulable. It is, because the goal set spans the DAG: a stale
    lint-cdc is picked up in the same turn and synthesis follows it. While the goal set
    narrowed to the failing proof this was the deadlock case — nothing would ever run
    lint-cdc, so the gate had to be taught to give up on it."""
    monkeypatch.chdir(tmp_path)
    _timing_fail_over_stale_synthesis("m")
    _valid("m", "lint-cdc", 1)
    _mk("m", "Design/lint-cdc/lint-report.txt", "drift")  # lint-cdc proof now invalid
    ev = facts.read_events("m")
    assert not facts.proof_valid("m", ev, "lint-cdc")
    assert "lint-cdc" in schedule.required_proofs(ev)
    d = schedule.decide("m")
    assert d["action"] == "DISPATCH" and d["rule"] == "lint-cdc"


def test_advisory_orders_two_stages_that_failed_together(tmp_path, monkeypatch):
    """Both ends of an advisory edge failing puts both in the goal set, so the cheap
    detector runs first instead of racing the expensive stage. A gate keyed on a caller-held
    mode took the opposite bet here from the one it takes when nothing is failing."""
    monkeypatch.chdir(tmp_path)
    _mk("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "simulation-plan", 1)
    _valid("m", "rtl-design", 1)
    _fail("m", "lint-cdc", 1, owner="rtl-design")
    _fail("m", "synthesis", 1, owner="rtl-design")
    _valid(
        "m", "rtl-design", 2, tag="fix"
    )  # one fix answers both; the owner has had its turn
    assert schedule.failing_proofs(facts.read_events("m")) == {"lint-cdc", "synthesis"}
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
    assert schedule.failing_proofs(facts.read_events("m")) == {"lint-cdc", "simulation"}
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
    _mk("m", "brainstorm.md", "b1")
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
        _valid("m", a["rule"], facts.runs_of(facts.read_events("m"), a["rule"]) + 1)
    assert seen[:2] == [
        "rtl-design",
        "lint-cdc",
    ]  # narrowed: the fix, then the re-verify
    assert a["action"] == "DONE"
    ev = facts.read_events("m")
    assert all(facts.proof_valid("m", ev, p) for p in rules.FORWARD_PRIORITY)


def test_signoff_all_valid_pinned_done(tmp_path, monkeypatch):
    # all 8 stage proofs valid with every oracle pinned -> objective=signoff is DONE,
    # meaning "the gate is clear, go stamp".
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1, oracle_grades=_PIN_ALL)
    assert schedule.decide("m", closing=True)["action"] == "DONE"


def test_closing_changes_what_done_means_not_which_proofs(tmp_path, monkeypatch):
    """`--closing` is a terminal predicate, not a scope. The same log and the same required
    proofs give opposite verdicts, and the gate is the whole of the difference — without it
    the flag would be a no-op reporting DONE with the trust boundary never consulted."""
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)  # default (proposed) grades — gate must refuse
    assert schedule.required_proofs(facts.read_events("m")) == set(
        rules.FORWARD_PRIORITY
    )
    assert schedule.decide("m")["action"] == "DONE"
    assert schedule.decide("m", closing=True)["action"] == "ESCALATE"


def test_signoff_gate_blocks_on_proposed_oracle(tmp_path, monkeypatch):
    # Every stage proof valid; default oracle grades leave several "proposed". The reason
    # must name the FIRST offender in FORWARD_PRIORITY order (specification) —
    # deterministic, never hash-seed-dependent set order.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("proposed", 1)
    a = schedule.decide("proposed", closing=True)
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
    # §6/A1-①: the sort predicate stays out of validity paths. power←timing is ADVISORY
    # (not an input edge): a power failure must stay an OPEN complaint even while the
    # timing proof is invalid, because only ADVISORY_ORDER's own consumer may read it.
    monkeypatch.chdir(tmp_path)
    _valid_chain_through_power("m")  # helper: power's ARTIFACT closure all valid
    _invalidate_proof("m", "timing-analysis")  # helper: drift a timing-only input
    _fail("m", "power-analysis", 1, owner="simulation")  # its own inputs untouched
    ev = facts.read_events("m")
    owed = schedule.owed(ev, schedule._failures("m", ev))
    assert [(f["rule"], f["owner"]) for f in owed] == [("power-analysis", "simulation")]


def test_two_hop_upstream_invalidity_does_not_discard_the_failure(
    tmp_path, monkeypatch
):
    # A1-② livelock regression, restated for v2. timing fails; rtl-design's proof (TWO hops
    # up via synthesis) is invalid while synthesis's is still valid. The old rule called such
    # a failure STALE and dropped it, which threw away its attribution; the open-complaint
    # rule keeps it and instead refuses to re-run the rule that raised it. Either way the
    # round must not spin: this envelope names nobody, so it is a human's call.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _valid("m", "synthesis", 1)
    _reopen("m", "semantic-review")  # rtl-design invalid; RTL bytes unchanged
    _fail("m", "timing-analysis", 1, owner=None)
    fails = schedule._failures("m", facts.read_events("m"))
    assert [(f["rule"], f["owners"]) for f in fails] == [("timing-analysis", [])]
    a = schedule.decide("m")
    assert a["action"] == "ESCALATE" and "named no fix_owner" in a["reason"]


def test_repair_rebuild_chain_dispatches_producer_first(tmp_path, monkeypatch):
    # A2 regression / §3.3 末句: repair on timing while the synthesis proof is invalid
    # -> the round rebuilds the PRODUCER, never ESCALATE. With lint-cdc already valid its
    # advisory edge is satisfied, so synthesis is the first thing the turn opens; the
    # unsatisfied case is test_advisory_predecessor_is_scheduled_rather_than_waited_on.
    monkeypatch.chdir(tmp_path)
    _write("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _valid("m", "lint-cdc", 1)
    _valid("m", "synthesis", 1)
    _reopen("m", "dc-shell")  # synthesis proof invalid, inputs still valid
    _fail("m", "timing-analysis", 1, owner="synthesis")
    a = schedule.decide("m")
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
    assert a["diagnosis_refs"] == ["d2"] and a["caused_by"] == [["simulation", 1]]


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
        # filelist.f is declared by simulation AND consumed by power-analysis's tb_env key.
        # Omitting it made power-analysis permanently unavailable here, so nothing in this
        # file ever forward-dispatched the last stage or reached DONE through step 2.
        "Verification/simulation/filelist.f",
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


def _sim_fail(module, run):
    """simulation read its logs and its reference model and still cannot attribute — the
    case `simulation/SKILL.md` calls "an answer rather than a shrug", and the only one that
    reaches the declared diagnostic."""
    _fail(module, "simulation", run, owner=None)


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
        _valid(module, rule, run, oracle_grade=grades.get(rule))


def test_failing_proofs_only_targets_stage_proofs(tmp_path, monkeypatch):
    # F3: only a PROOF can be re-verified, and simulation-triage produces none. Even if a
    # triage outcome ever carries verdict=fail it must not narrow the goal set — else
    # step-2's sorted(work, key=FORWARD_PRIORITY.index) raises ValueError.
    monkeypatch.chdir(tmp_path)
    _outcome(
        "m", "simulation-triage", 1, "fail", {}, []
    )  # non-proof rule, newest outcome
    assert schedule.failing_proofs(facts.read_events("m")) == set()
    req = schedule.required_proofs(facts.read_events("m"))
    assert "simulation-triage" not in req
    assert req == set(rules.FORWARD_PRIORITY)


def test_decide_repair_survives_triage_fail_outcome(tmp_path, monkeypatch):
    # F3 symptom: with the whole delivery chain valid and a (buggy) newest triage fail
    # outcome, decide(repair) must not crash — before the fix, required_proofs returns
    # {"simulation-triage"} and step 2 hits FORWARD_PRIORITY.index("simulation-triage").
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _outcome("m", "simulation-triage", 1, "fail", {}, [])
    a = schedule.decide("m")  # must not raise ValueError
    assert a["action"] in ("DONE", "YIELD", "DISPATCH", "ESCALATE")
    assert a.get("rule") != "simulation-triage"


def test_unregistered_rule_in_flight_is_not_reapable_forever(tmp_path, monkeypatch):
    # An in-flight dispatch naming a rule the registry does not know is unreapable —
    # `reap --rule` argparse-rejects it — so surfacing it would wedge the module behind a
    # `REAP` decide keeps returning and no one can execute. in_flight drops it instead.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)
    _dispatch("m", "not-a-rule", 1, {})  # never reaped
    assert facts.in_flight(facts.read_events("m")) == []
    assert schedule.decide("m")["action"] == "DONE"


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
    assert schedule.decide("m")["action"] == "YIELD"


def test_sim_fail_triage_in_flight_is_not_dispatched_twice(tmp_path, monkeypatch):
    # E5 / §6: ambiguous sim failure with simulation-triage already in flight -> no second
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
    _mk("m", "brainstorm.md", "b1")
    _valid("m", "specification", 1)
    _valid("m", "rtl-design", 1)
    _mk("m", "Design/rtl-design/semantic-review/child.md", "drift")  # rtl proof invalid
    _dispatch("m", "lint-cdc", 1, {})  # in-flight consumer of Design/rtl-design/*.v
    d = schedule.decide("m")
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
    d = schedule.decide("m")
    assert not (d["action"] == "DISPATCH" and d["rule"] == "rtl-design")
    assert d["action"] in ("YIELD", "DISPATCH")  # YIELD, or a different safe candidate


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
# Condition 3 leans two ways when re-derived: anchored on the outcome instead of the dispatch
# it is too loose, without the live-pin conjunct too tight. These pin the three scenarios that
# separate them.


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
    _, outcome = facts._proof_outcome(events, "specification")
    assert schedule._oracle_retracted(events, "specification", outcome)
    assert schedule.decide("m")["action"] == "ESCALATE"


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
    _, outcome = facts._proof_outcome(events, "specification")
    assert schedule._oracle_retracted(events, "specification", outcome)
    assert schedule.decide("m")["action"] == "ESCALATE"


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
    _, outcome = facts._proof_outcome(events, "specification")
    assert not schedule._oracle_retracted(events, "specification", outcome)
    assert [f["rule"] for f in schedule._failures("m", events)] == ["specification"]


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
    assert a["action"] == "ESCALATE", (
        f"a verdict whose judge was reopened must not direct rework at all; got {a}"
    )
    assert "reopened" in a["reason"]


# ── §O: the gate says whether; the basis says what ────────────────────────────
def _all_valid_and_pinned(module):
    _build_all_valid(module, 1)
    for rule in rules.FORWARD_PRIORITY:
        if rules.RULES[rule].oracle[1] == "proposed":
            _pin(module, rule)
    assert facts.signoff_gate(module, facts.read_events(module)) is None


def test_basis_covers_every_proof_in_forward_order(tmp_path, monkeypatch):
    # A signoff record whose row order varied by hash seed would not be a record.
    monkeypatch.chdir(tmp_path)
    _all_valid_and_pinned("m")
    basis = facts.signoff_basis("m", facts.read_events("m"))
    assert [b["proof"] for b in basis] == list(rules.FORWARD_PRIORITY)


def test_basis_grades_each_oracle_and_names_what_a_human_endorsed(
    tmp_path, monkeypatch
):
    # The two things a signature rests on: which trust class each oracle is, and — for the
    # human ones — the content fingerprint the pin actually named. "graded human" without
    # the fingerprint does not say human-endorsed WHAT.
    monkeypatch.chdir(tmp_path)
    _all_valid_and_pinned("m")
    events = facts.read_events("m")
    by_proof = {b["proof"]: b for b in facts.signoff_basis("m", events)}
    for rule_name, rule in rules.RULES.items():
        if rule_name not in by_proof:
            continue
        o = by_proof[rule_name]["oracle"]
        assert o["ref"] == rule.oracle[0]
        assert o["grade"] in ("tool", "human")
        if rule.oracle[1] == "proposed":
            # pinned here, so human — and the fingerprint must be the oracle's CURRENT content
            assert o["grade"] == "human"
            assert o["pinned_fingerprint"] == facts.oracle_content_fp("m", rule)
        else:
            # a tool oracle is never pinned; claiming a fingerprint would invent an endorsement
            assert o["grade"] == "tool"
            assert "pinned_fingerprint" not in o


def test_basis_drops_the_fingerprint_when_the_pin_is_reopened(tmp_path, monkeypatch):
    # Withdrawing the endorsement must withdraw the claim that something was endorsed, not
    # leave a stale fingerprint standing next to a downgraded grade.
    monkeypatch.chdir(tmp_path)
    _all_valid_and_pinned("m")
    assert (
        facts.signoff_basis("m", facts.read_events("m"))[0]["oracle"]["grade"]
        == "human"
    )
    _reopen("m", rules.RULES["specification"].oracle[0])
    spec = facts.signoff_basis("m", facts.read_events("m"))[0]
    assert spec["oracle"]["grade"] == "proposed"
    assert "pinned_fingerprint" not in spec["oracle"]


def test_basis_names_the_input_set_each_verdict_was_about(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _all_valid_and_pinned("m")
    events = facts.read_events("m")
    by_proof = {b["proof"]: b for b in facts.signoff_basis("m", events)}
    spec = by_proof["specification"]
    assert spec["inputs"] == ["brainstorm.md"]
    # and it matches what the proof actually recorded, not a re-derivation from rules.py
    _, outcome = facts._proof_outcome(events, "specification")
    proof = next(p for p in outcome["proofs"] if p["name"] == "specification")
    assert spec["inputs"] == sorted(proof["inputs"])


def test_decide_signoff_done_carries_the_basis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _all_valid_and_pinned("m")
    a = schedule.decide("m", closing=True)
    assert a["action"] == "DONE"
    assert [b["proof"] for b in a["basis"]] == list(rules.FORWARD_PRIORITY)


def test_decide_signoff_escalate_carries_no_basis(tmp_path, monkeypatch):
    # Nothing is being endorsed when the gate blocks; a basis there would read as an offer.
    monkeypatch.chdir(tmp_path)
    _build_all_valid("m", 1)  # proposed oracles -> gate blocks
    a = schedule.decide("m", closing=True)
    assert a["action"] == "ESCALATE" and "basis" not in a
