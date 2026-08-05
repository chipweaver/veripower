"""VeriPower scheduler — exactly one action per call. Pure over (disk, ledger, args): no
state of its own, and nothing the caller has to carry between turns.

Two questions carry the whole repair path, and the order between them is the design:

  1. WHO must act on each failure. One veto (the oracle that judged it was reopened —
     a retracted judge cannot direct rework) and three sources, most authoritative first:
     any analysis of this failure, then the failing stage's own envelope, then the
     diagnostic the registry declares for that stage. If none of them names anyone, the
     round STOPS and asks a human — attribution is clarified before anything is scheduled,
     so nothing downstream of that point has to reason about an unclear failure.
  2. HAS THEY ACTED — the owner dispatched since the failure landed. That is the only
     thing that closes a failure. Input drift deliberately does not: a sibling repair
     moving a failure's inputs does not make the fix owner's job go away, and treating it
     as if it did is how an attribution that is written down, legal and unanswered gets
     discarded and then rediscovered by spending the stage that raised it again.

Everything else follows: failures sharing an owner are one dispatch (a group-by, not a
merge rule), and a failure still owed against a rule keeps that rule from running at all.

Bare-importable (`import schedule`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import facts  # noqa: E402
import rules  # noqa: E402

# The stage-proof set, in FORWARD_PRIORITY order. Filtering on .proof (not just aliasing
# FORWARD_PRIORITY) keeps a future non-proof rule that slips into FORWARD_PRIORITY from being
# treated as a stage proof (test_rules anchors the invariant).
_STAGE_PROOFS = [r for r in rules.FORWARD_PRIORITY if rules.RULES[r].proof]


def failing_proofs(events: list[dict]) -> set[str]:
    """The stage proofs whose LATEST outcome is a fail.

    Scan newest-first: the first outcome seen per rule IS that rule's latest. Position by
    scan order — never events.index (duplicate event lines collide, and it's O(n) per call).
    Restricted to the eight stage proofs: a non-proof rule (simulation-triage) has no proof
    to re-verify and would crash the FORWARD_PRIORITY.index sort (spec §2/§3.2).

    ALL of them, not the newest one. A failure that is not in this set is not scheduled, so
    returning a single rule leaves every other failing rule out of the round — two stages
    that fail together get their fix merged into one dispatch and then re-verify one after
    the other, even with no artifact edge between them."""
    out: set[str] = set()
    seen: set[str] = set()
    for e in reversed(events):
        if e["type"] == "outcome" and e["rule"] in _STAGE_PROOFS:
            if e["rule"] not in seen:
                seen.add(e["rule"])
                if e["verdict"] == "fail":
                    out.add(e["rule"])
    return out


def required_proofs(events: list[dict]) -> set[str]:
    """The proofs this round must make valid: all eight, whatever is failing.

    Not narrowed to the failing ones. What must not be built during a repair is already said
    by three filters, each naming a reason: `facts.rule_available` (the producer's proof is
    invalid), `owed_rules` (nobody has answered for it), `_unblocked` (its producer is in
    flight or is a co-candidate). Narrowing added only the siblings — a lint or a synthesis
    stale from the same edit with no artifact edge to the failure — and holding those back
    trades machine time that was idle anyway for finding out later.

    Signoff does not appear here. It requires the same proofs at a stricter bar
    (facts.signoff_gate at decide's DONE, step 3), which is a question about when the work
    is finished rather than about which work there is."""
    return set(_STAGE_PROOFS)


def _latest_fail(events: list[dict], rule: str) -> tuple[int, dict] | None:
    """(position, outcome) of the rule's latest outcome iff it is a fail."""
    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        if e["type"] == "outcome" and e["rule"] == rule:
            return (i, e) if e["verdict"] == "fail" else None
    return None


def _active_diagnoses(events: list[dict], rule: str, outcome: dict) -> list[dict]:
    """ALL diagnoses effective for this failure (subject matches this outcome's run,
    not superseded), oldest first. NO fix_owner filter: a self-pointing diagnosis
    (fix_owner absent, attribution = the failed rule's own judge) is still a 现成归因 —
    the reliability gate escalates it instead of auto-rebuilding (§3.3 bullet 4)."""
    sup = {
        e["supersedes"]
        for e in events
        if e["type"] == "diagnosis" and e.get("supersedes")
    }
    return [
        e
        for e in events
        if e["type"] == "diagnosis"
        and e["id"] not in sup
        and e["subject"]["proof"] == rule
        and e["subject"]["outcome_run"] == outcome["run"]
    ]


def _reliable(diag: dict) -> bool:
    """§3.4: reliable iff it names a rebuild target at all, AND either a human authored it
    (终审) or a triage run called it high-confidence.

    An oracle-side attribution — the failed rule blaming its own judge — is caught by the
    first clause and needs no separate test, because neither writer can produce one with a
    `fix_owner`. `kernel.cmd_diagnose` rejects a `fix_owner` outside the subject's input
    closure, `kernel._derive_triage` only writes one when the root cause is inside it, and
    the graph is acyclic, so no rule is ever in its own closure."""
    if not diag.get("fix_owner"):
        return False
    if diag["source"] == "human":
        return True
    return diag.get("confidence") == "high"


def _declared_owner(module: str, rule: str) -> str | None:
    """`stage_specific.fix_owner` from the failed rule's canonical result.json, VERBATIM: the
    rule its own envelope says must act, legal or not. None when the envelope names nobody
    (including an unreadable or absent envelope).

    Reading canonical is sound for a complaint: a complaint exists only while the rule's
    LATEST outcome is that fail, and a fail promotes, so canonical holds that run's envelope.
    (A `blocked` run does not promote — and mints no complaint either.)"""
    p = facts.module_root(module) / Path(*rules.workdir_root(rule)) / "result.json"
    try:
        ss = json.loads(p.read_text()).get("stage_specific", {})
    except (OSError, ValueError):
        return None
    owner = ss.get("fix_owner")
    return owner if owner in rules.RULES else None


def _legal(rule: str, name: str | None) -> bool:
    """A name is a legal auto-rebuild target iff it produces something inside the failed
    rule's TRANSITIVE input closure. Naming itself is excluded by construction (no rule is in
    its own closure), which is also why naming itself means the in-stage remedy is exhausted:
    a defect the stage could fix from here is fixed WITHIN its run."""
    return bool(name) and name in rules.input_closure(rule)


def _event_index(events: list[dict], event: dict) -> int:
    """Position of `event` in the log, by identity — never `.index()`, which compares by
    value and would collide on two structurally identical records."""
    for i, e in enumerate(events):
        if e is event:
            return i
    return 0


def _oracle_retracted(events: list[dict], rule: str, outcome: dict) -> bool:
    """True iff the oracle that judged this failure was reopened after the run executed and
    has not since been re-pinned — §4.4 condition 3, asked of a fail rather than a pass.

    Reopening an oracle says "I no longer stand behind this judge". A pass loses its proof;
    a fail loses its AUTHORITY — it can no longer direct rework at an upstream stage on that
    judge's word. So the failure keeps existing and goes to a human, rather than being
    quietly treated as if it had not happened."""
    proof = next((p for p in outcome["proofs"] if p["name"] == rule), None)
    if proof is None or not rules.RULES[rule].oracle:
        return False
    oref = proof["oracle"]["ref"]
    d_idx = facts._dispatch_index(events, rule, outcome["run"])
    anchor = d_idx if d_idx is not None else 0
    return facts._reopened_after(events, oref, anchor) and not facts.live_pins(
        events, oref
    )


def _owner(module: str, events: list[dict], rule: str, idx: int, outcome: dict) -> dict:
    """WHO must act on this failure — one veto, then three sources, most authoritative first.

    Returns `attribution` (what was written, verbatim), `owners` (its routable projection,
    possibly empty) and `unreliable` (candidates to show a human). The four escalation
    reasons are readings of the first two, so no branch has to raise its own.

    `owners` is a LIST: one failure can need more than one stage to move, and an analysis
    says so with one diagnosis per independent root cause (the log already permits several
    against one outcome, and `_active_diagnoses` already returns all of them).

    Each entry carries its own `since`: the event position from which "has this owner acted"
    is measured, which is where THAT naming became known rather than where the failure
    landed. They differ whenever an analysis names someone already dispatched for an
    unrelated reason — that round could not have acted on information that did not exist yet,
    so counting it would close the failure with nobody ever told about it.

    The analysis source is TERMINAL, not a fallthrough: an analysis that came back unsure
    has spoken, and its answer is "nobody". Letting it fall through would reach the
    diagnostic rung again and re-run the same analyzer over the same evidence forever. One
    unsure entry among several makes the whole failure unclear: part of it has no owner, and
    a half-known attribution is what the early exit exists to keep out of scheduling."""
    if _oracle_retracted(events, rule, outcome):
        return {
            "attribution": None,
            "owners": [],
            "unreliable": [],
            "retracted": True,
        }
    base = {"retracted": False}
    diags = _active_diagnoses(events, rule, outcome)
    if diags:  # source 1: a later analysis outranks the stage's own self-report
        if not all(_reliable(d) for d in diags):
            return {
                **base,
                "attribution": diags[-1]["attribution"],
                "owners": [],
                "unreliable": [d for d in diags if not _reliable(d)],
            }
        owners = {}
        for d in diags:
            o = owners.setdefault(
                d["fix_owner"], {"owner": d["fix_owner"], "since": idx, "diagnoses": []}
            )
            o["since"] = max(o["since"], _event_index(events, d))
            o["diagnoses"].append(d)
        return {
            **base,
            "attribution": diags[-1]["attribution"],
            "owners": sorted(owners.values(), key=lambda o: o["since"]),
            "unreliable": [],
        }
    named = _declared_owner(module, rule)  # source 2: the failing stage's own envelope
    if named:
        return {
            **base,
            "attribution": named,
            "owners": (
                [{"owner": named, "since": idx, "diagnoses": []}]
                if _legal(rule, named)
                else []
            ),
            "unreliable": [],
        }
    # source 3: nobody named anyone, so the stage's declared diagnostic must find out
    triage = rules.RULES[rule].triage
    return {
        **base,
        "attribution": None,
        "owners": [{"owner": triage, "since": idx, "diagnoses": []}] if triage else [],
        "unreliable": [],
    }


def _answered(events: list[dict], since: int, owner: str) -> bool:
    """True iff the owner has been dispatched since this naming became known, and that run
    did not die. This — not input freshness — is what closes a failure.

    Dispatch, not delivery: the question is whether the party that must act has had its turn.
    A round that rebuilt the owner for some other reason still had the chance, and asking it
    again would spend the stage twice on one defect; the same argument covers an out-of-band
    edit answered by the next rebuild. A run reaped `blocked` is the exception — nothing
    landed, so the complaint re-opens rather than being silently consumed by a dead executor."""
    for i, e in enumerate(events):
        if i <= since or e["type"] != "dispatch" or e["rule"] != owner:
            continue
        done = next(
            (
                o
                for o in events[i + 1 :]
                if o["type"] == "outcome"
                and o["rule"] == owner
                and o["run"] == e["run"]
            ),
            None,
        )
        if done is None or done["verdict"] != "blocked":
            return True
    return False


def _failures(module: str, events: list[dict]) -> list[dict]:
    """Every proof whose latest outcome is a fail, in FORWARD_PRIORITY order, each carrying
    who must act on it. No filtering — the caller decides what to do with an unclear one and
    what to do with one already answered."""
    out = []
    for rule in rules.FORWARD_PRIORITY:
        hit = _latest_fail(events, rule)
        if hit is None:
            continue
        idx, outcome = hit
        out.append(
            {
                "rule": rule,
                "run": outcome["run"],
                "idx": idx,
                **_owner(module, events, rule, idx, outcome),
            }
        )
    return out


def owed(events: list[dict], fails: list[dict]) -> list[dict]:
    """What is still owed: one entry per (failure, owner) whose owner has not been dispatched
    since that naming landed.

        owed(f, o) = not _answered(o)

    Still one clause. Flattening here rather than carrying the list downstream is what leaves
    the rest untouched: `_group` buckets by `owner`, so a failure needing two stages lands in
    two buckets. Callers must have cleared the unclear ones first (`decide` escalates on
    them), so every failure reaching here has at least one owner."""
    out = []
    for f in fails:
        rest = {k: v for k, v in f.items() if k != "owners"}
        for o in f["owners"]:
            if not _answered(events, o["since"], o["owner"]):
                out.append({**rest, **o})
    return out


def _attribute_args(module: str, c: dict, supersedes: str | None = None) -> list[str]:
    """The `kernel.py diagnose` argv that answers this escalation. Only the fields the
    scheduler knows — the rest the human fills from `--help`."""
    legal = (
        ", ".join(sorted(rules.input_closure(c["rule"]))) or "nothing: closure is empty"
    )
    args = [
        "diagnose",
        "--module",
        module,
        "--subject-proof",
        c["rule"],
        "--subject-run",
        str(c["run"]),
        "--fix-owner",
        f"<{legal}>",
    ]
    return args + (["--supersedes", supersedes] if supersedes else [])


def _escalation(module: str, c: dict) -> dict:
    """Why a complaint cannot be routed, derived from `(attribution, owner)` rather than
    raised where it was noticed — so the three namings and the unreliable diagnosis read as
    one classification instead of four scattered branches.

    Each carries `remedy`: the argv that unblocks it. A round that stops the whole pipeline
    has to say what reopens it, or the reader reaches for a verb that does not."""
    rule, named = c["rule"], c["attribution"]
    if c.get("retracted"):
        return {
            "rule": rule,
            "reason": f"{rule}: the oracle that judged this failure was reopened",
            # re-endorsing the judge, not re-attributing: the retraction is checked ahead of
            # any diagnosis (`_owner`), so a fresh one would not be consulted
            "remedy": ["pin", "--module", module, "--rule", rule],
        }
    if c["unreliable"]:
        return {
            "rule": rule,
            "reason": f"unreliable diagnosis for {rule}",
            "candidates": [
                {
                    "attribution": d["attribution"],
                    "confidence": d.get("confidence"),
                    "diagnosis": d["id"],
                }
                for d in c["unreliable"]
            ],
            "remedy": _attribute_args(module, c, c["unreliable"][-1]["id"]),
        }
    if named is None:
        return {
            "rule": rule,
            "reason": f"{rule}: envelope named no fix_owner",
            "remedy": _attribute_args(module, c),
        }
    if named == rule:
        return {
            "rule": rule,
            "reason": f"{rule}: fix_owner is itself, in-stage remedy exhausted",
            "remedy": _attribute_args(module, c),
        }
    return {
        "rule": rule,
        "reason": f"{rule}: fix_owner {named!r} is outside its input closure",
        "remedy": _attribute_args(module, c),
    }


def _workdir_of(events, rule, run):
    for e in events:
        if e["type"] == "dispatch" and e["rule"] == rule and e["run"] == run:
            return e["workdir"]
    return None


def _executor_wrote(module: str, events: list[dict], rule: str, run: int) -> bool:
    """Has anything landed in this run's workdir that the dispatch itself did not put there.

    `dispatch` marks a run open; it does not prove a process is running, and a turn that never
    launched its executor reads exactly like a stage still working. `dispatch.json` is the
    newest thing a dispatch leaves behind (`store.carry_self` copies with copy2, keeping the
    source mtimes), so anything newer came from an executor. Comparing inside one directory
    rather than against the event's timestamp keeps `decide` free of the clock."""
    root = facts.module_root(module) / (_workdir_of(events, rule, run) or "")
    try:
        opened = (root / "dispatch.json").stat().st_mtime_ns
    except OSError:
        return False
    return any(
        p.is_file() and not p.is_symlink() and p.stat().st_mtime_ns > opened
        for p in root.rglob("*")
        if p.name != "dispatch.json"
    )


def _unblocked(rule_name: str, pending: set[str], inflight: list[dict]) -> bool:
    """Nothing this rule depends on is about to change under it.

    `pending` = what is in flight plus the other candidates this round. Three clauses, and
    the asymmetries are the design:

    * a producer IN FLIGHT is a physical hazard — it is rewriting its products while this
      rule would be reading them. Transitive, and it applies to every rule.
    * a producer that is merely a CO-CANDIDATE is a logical one: this round's OUTPUT would
      be invalidated by the other one. So it binds only on a rule that produces a proof —
      a rule with none (the diagnostic) analyses one frozen past run and lands a diagnosis
      bound to it, and nothing an upstream rebuild does can invalidate that. Holding it
      anyway costs the analysis a whole repair cycle: the owner it would have named stays
      unknown, so the round that fixes the other failure cannot fix this one too.
    * a CONSUMER in flight is the torn read: promoting a new version under its canonical
      read. In-flight only, never co-candidates — applied to co-candidates it would
      deadlock, each of a producer/consumer pair held by the other, and for them the first
      clause already says the right thing: producer first, consumer next round.

    Pure: the closure is a registry query."""
    closure = rules.input_closure(rule_name)
    running = {f["rule"] for f in inflight}
    if any(r in closure for r in running):
        return False
    if rules.RULES[rule_name].proof and any(
        p != rule_name and p in closure for p in pending - running
    ):
        return False
    return not any(rule_name in rules.input_closure(r) for r in running)


def _held_by_advisory(
    module: str,
    events: list[dict],
    rule: str,
    coming: set[str],
    inflight: list[dict],
) -> bool:
    """No-overtake gate (§3.3): hold `rule` back while an `ADVISORY_ORDER` predecessor of it
    is not yet valid AND is going to speak — scheduled this round (`coming`) or already
    running. The sole consumer of advisory data.

    An advisory edge is a bet that the cheap detector will answer before the expensive stage
    spends a run on inputs it is about to invalidate. The bet is only available while the
    detector is actually coming: a predecessor that is neither scheduled nor running will
    never resolve, so holding for it is waiting on nothing.

    Only ADVISORY_ORDER is read, never input_producers: `rule_available`, checked beside
    this, already implies every input producer's proof is valid."""
    coming = coming | {f["rule"] for f in inflight}
    for p in rules.ADVISORY_ORDER.get(rule, ()):
        if p in coming and not facts.proof_valid(module, events, rules.RULES[p].proof):
            return True
    return False


def _forward_work(module: str, events: list[dict], required: set[str]) -> set[str]:
    """The required proofs that are not currently valid, expanded to the REBUILD CLOSURE.
    §3.3 末句: a narrowed rebuild chain (timing -> rebuild synthesis FIRST) walks the
    producers of unavailable inputs; when nothing is failing the required set already spans
    the DAG, so the expansion is usually a no-op."""
    work = {p for p in required if not facts.proof_valid(module, events, p)}
    frontier = set(work)
    while frontier:
        nxt = set()
        for rule in frontier:
            if facts.rule_available(module, events, rule):
                continue
            for prod in rules.input_producers(rule):
                pr = rules.RULES[prod]
                needs = (
                    pr.proof and not facts.proof_valid(module, events, pr.proof)
                ) or not facts.rule_available(module, events, prod)
                if needs and prod not in work:
                    work.add(prod)
                    nxt.add(prod)
        frontier = nxt
    return work


def _dispatched(module: str, action: dict) -> dict:
    """A DISPATCH action, plus the exact `kernel.py dispatch` argv that executes it.

    Every field the dispatch needs was just computed here. Re-serialising them by hand in
    the Orchestrator's turn is a transcription step between two machine endpoints, and the
    only thing that ever guarded it was prose telling the transcriber not to drop an entry —
    a multi-cause rework that loses one `caused_by` silently leaves that failure to re-fail
    next pass. Emitting the argv removes the step rather than warning about it; the fields
    stay in the action too, because a reader of the log wants them named, not parsed."""
    action = dict(action)
    args = [
        "dispatch",
        "--module",
        module,
        "--rule",
        action["rule"],
    ]
    for cb_rule, cb_run in action.get("caused_by", []):
        args += ["--caused-by", f"{cb_rule}:{cb_run}"]
    if action.get("diagnosis_refs"):
        args += ["--diagnosis-refs", ",".join(action["diagnosis_refs"])]
    if action.get("params"):
        args += ["--params", json.dumps(action["params"], sort_keys=True)]
    action["dispatch_args"] = args
    return action


def _ready_to_reap(module, events, inflight, wake):
    """Step 0: a run whose result is already on disk, or one `--wake` names. Reaping before
    deciding keeps every later step reading a current log.

    `--wake` earns its keep only on the branch the scan cannot serve: an executor that died
    without writing `result.json` is invisible to the scan, and the ledger would YIELD on it
    forever."""
    if wake and ":" in wake:
        r, _, n = wake.partition(":")
        if n.isdigit() and {"rule": r, "run": int(n)} in inflight:
            return {"action": "REAP", "rule": r, "run": int(n)}
    ready = [
        f
        for f in inflight
        if (
            facts.module_root(module)
            / (_workdir_of(events, f["rule"], f["run"]) or "")
            / "result.json"
        ).is_file()
    ]
    if not ready:
        return None
    ready.sort(
        key=lambda f: (
            rules.FORWARD_PRIORITY.index(f["rule"])
            if f["rule"] in rules.FORWARD_PRIORITY
            else 99
        )
    )
    return {"action": "REAP", "rule": ready[0]["rule"], "run": ready[0]["run"]}


def _group(owed_: list[dict]) -> dict[str, list[dict]]:
    """`{owner -> [the failures it is owed]}`.

    "Failures naming one owner become one dispatch" is what this returns, not a rule applied
    to it — there is no sieve that could be implemented half-way. The declared diagnostic is
    in here too: it is an ordinary owner, reached by the third source in `_owner`."""
    out: dict[str, list[dict]] = {}
    for f in owed_:
        out.setdefault(f["owner"], []).append(f)
    return out


def _candidates(module, events, inflight, repair, owed_rules, work):
    """Every rule that could start right now, best first.

    Repairing and building are the same act — dispatch a rule, hand it the failures it is
    owed — so one set is ordered rather than two staged."""
    pool = (work | set(repair)) - owed_rules - {f["rule"] for f in inflight}
    # `coming`, for the advisory gate: a rule held out of the pool is not going to speak
    # this round, and an advisory hold that waits for it waits forever.
    startable = [
        r
        for r in pool
        if facts.rule_available(module, events, r)
        and not _held_by_advisory(module, events, r, pool, inflight)
    ]
    pending = {f["rule"] for f in inflight} | set(startable)
    out = [r for r in startable if _unblocked(r, pending, inflight)]
    return sorted(
        out,
        key=lambda r: (
            # answer a failure before building anything: a proof still owed against is going
            # to be re-verified either way, and doing it before the fix lands spends it twice
            0 if r in repair else 1,
            # a `task` executor returns immediately and a `main-thread` Skill() blocks the
            # turn, so starting the async one first is what makes two independent stages
            # overlap. Safe because `_unblocked` left an antichain: reordering an antichain
            # reorders nothing that had an order.
            0 if rules.RULES[r].execution == "task" else 1,
            rules.FORWARD_PRIORITY.index(r) if r in rules.FORWARD_PRIORITY else -1,
        ),
    )


def _dispatch_action(module, rule, repair):
    """The DISPATCH, carrying every failure this round is answerable for."""
    action = {
        "action": "DISPATCH",
        "rule": rule,
        "execution": rules.RULES[rule].execution,
    }
    group = repair.get(rule, [])
    if group:
        action["caused_by"] = [[f["rule"], f["run"]] for f in group]
        refs = [d["id"] for f in group for d in f["diagnoses"]]
        if refs:
            action["diagnosis_refs"] = refs
        # A rule that declares params is being dispatched AT one of these failures — today
        # only the diagnostic, which needs the run it must open.
        if "sim_run" in rules.RULES[rule].params:
            action["params"] = {"sim_run": group[0]["run"]}
    return _dispatched(module, action)


def _settle(module, events, inflight, required, closing):
    """Nothing can start. Say why, in the order that makes the reason true."""
    if inflight:
        # `dispatched_at` beside `executor_wrote` is the whole report: how long is too long
        # is the reader's call, so no elapsed time is computed and `decide` stays pure.
        return {
            "action": "YIELD",
            "in_flight": [
                {
                    **f,
                    "dispatched_at": events[
                        facts._dispatch_index(events, f["rule"], f["run"])
                    ]["ts"],
                    "executor_wrote": _executor_wrote(
                        module, events, f["rule"], f["run"]
                    ),
                }
                for f in inflight
            ],
        }
    if all(facts.proof_valid(module, events, p) for p in required):
        if closing:
            # `closing` changes nothing about WHICH proofs are required — only what a clear
            # board means. Without it, DONE says the DAG is built; with it, DONE says the
            # trust boundary is clear and the human may stamp. A blocked gate is an ESCALATE
            # rather than a field on DONE deliberately: the Orchestrator must execute an
            # action, and the pin it needs would be one more returned value nobody read.
            reason = facts.signoff_gate(module, events)
            if reason is not None:
                return {"action": "ESCALATE", "reason": reason}
            # "go stamp" is where the human decides; hand them the proposition, not just
            # the permission (facts.signoff_basis).
            return {"action": "DONE", "basis": facts.signoff_basis(module, events)}
        return {"action": "DONE"}
    return {
        "action": "ESCALATE",
        "reason": "no eligible rule, none in-flight, not done",
    }


def decide(
    module: str,
    *,
    wake: str | None = None,
    closing: bool = False,
) -> dict:
    """Four steps, first one that can act wins."""
    events = facts.read_events(module)
    inflight = facts.in_flight(events)

    reap = _ready_to_reap(module, events, inflight, wake)
    if reap:
        return reap

    fails = _failures(module, events)
    unclear = [f for f in fails if not f["owners"]]
    if unclear:
        # Attribution is clarified BEFORE anything is scheduled. One at a time, earliest
        # first: a failure nobody can attribute only arises on a parallel branch, and
        # parallel runs do not land together, so a round discovers one of them at a time.
        return {"action": "ESCALATE", **_escalation(module, unclear[0])}
    # ↓ every failure below this line has an owner
    owed_ = owed(events, fails)

    repair = _group(owed_)
    # A rule still owed against does not run, in either role: re-verifying a proof whose
    # failure nobody has answered spends the stage to rediscover what is already written
    # down, and rebuilding a rule that is itself owed against answers nothing.
    owed_rules = {f["rule"] for f in owed_}
    required = required_proofs(events)
    candidates = _candidates(
        module,
        events,
        inflight,
        repair,
        owed_rules,
        _forward_work(module, events, required),
    )
    if candidates:
        return _dispatch_action(module, candidates[0], repair)

    return _settle(module, events, inflight, required, closing)
