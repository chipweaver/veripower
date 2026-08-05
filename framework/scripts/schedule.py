"""VeriPower scheduler — exactly one action per call. Pure over (disk, ledger, args): no
state of its own, and nothing the caller has to carry between turns.

One concept carries the whole repair path: a **complaint**. A proof whose latest outcome is
a fail is a complaint; it is OPEN until something has been done about it, and while it is
open the scheduler's job is to hand it to the party that must act. Everything the old
disposition tree decided by branching — merge or not, route or re-verify, escalate or
triage — is a query over the open complaint set:

  * its OWNER is one field pair, `(attribution, fix_owner)`, read from ONE function that
    knows both channels (the failing envelope's self-report, and any diagnosis that
    superseded it). The scheduler reads no other attribution field.
  * complaints sharing an owner are one dispatch. That is a group-by, not a merge rule, so
    there is no sieve to get half right.
  * a complaint OPEN against a rule blocks that rule from running at all: re-verifying a
    proof whose failure nobody has answered spends the stage to rediscover what is already
    written down.

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
    """The proofs this round must make valid: the ones currently failing, or all eight.

    One concept, derived, carried by nobody. While a proof is failing it IS the goal —
    nothing downstream of it means anything until it re-verifies, so building the rest is
    work that a second failure would only invalidate again. When the last one re-verifies
    the set empties on its own and the goal widens back to the whole DAG; there is no
    transition to hold in a session, and no way to be left in the narrow mode after the
    thing that narrowed it is gone.

    Signoff does not appear here. It requires the same proofs at a stricter bar
    (facts.signoff_gate at decide's DONE, step 3), which is a question about when the work
    is finished rather than about which work there is."""
    return failing_proofs(events) or set(_STAGE_PROOFS)


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


def _attribution(module: str, events: list[dict], rule: str, outcome: dict) -> dict:
    """`(attribution, owner, diagnoses)` for one failure — the SINGLE shape both attribution
    channels reduce to, and the only thing the scheduler reads about why a stage failed.

    `attribution` is what was written, verbatim; `owner` is its routable projection, present
    only when the naming is legal AND (for a diagnosis) reliable. Every branch the old
    disposition tree took over these two channels is a condition on this pair, so an
    escalation reason is derivable from it rather than raised at the branch that noticed.

    Precedence: a later analysis outranks the stage's own self-report. `_active_diagnoses`
    is already scoped to this outcome's run, so a diagnosis of an older run cannot speak."""
    diags = _active_diagnoses(events, rule, outcome)
    if diags:
        latest = diags[-1]
        if _reliable(latest):
            owner = latest["fix_owner"]
            return {
                "attribution": latest["attribution"],
                "owner": owner,
                "diagnoses": [
                    d for d in diags if _reliable(d) and d["fix_owner"] == owner
                ],
                "unreliable": [],
            }
        return {
            "attribution": latest["attribution"],
            "owner": None,
            "diagnoses": [],
            "unreliable": diags,
        }
    named = _declared_owner(module, rule)
    return {
        "attribution": named,
        "owner": named if _legal(rule, named) else None,
        "diagnoses": [],
        "unreliable": [],
    }


def _answered(events: list[dict], idx: int, owner: str) -> bool:
    """True iff the owner has been dispatched since this failure landed, and that run did not
    die. This — not input freshness — is what closes a complaint.

    Dispatch, not delivery: the question is whether the party that must act has had its turn.
    A round that rebuilt the owner for some other reason still had the chance, and asking it
    again would spend the stage twice on one defect; the same argument covers an out-of-band
    edit answered by the next rebuild. A run reaped `blocked` is the exception — nothing
    landed, so the complaint re-opens rather than being silently consumed by a dead executor."""
    for i, e in enumerate(events):
        if i <= idx or e["type"] != "dispatch" or e["rule"] != owner:
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


def complaints(module: str, events: list[dict]) -> list[dict]:
    """The OPEN complaints, in FORWARD_PRIORITY order.

    A failure is open while there is a specific thing to do about it that has not been done:

    * its verdict must still describe reality (`facts.verdict_trustworthy` — the run's own
      products, and the judge that reached the verdict). A reopened oracle retracts a failure
      exactly as it retracts a pass.
    * OWNED: open until the owner has been dispatched (`_answered`). Input drift is
      deliberately NOT a closer — a sibling repair moving this failure's inputs does not make
      the fix owner's job go away, and treating it as one is how an attribution that is
      written down, legal, and unanswered gets thrown away and then rediscovered by spending
      the stage again.
    * UNOWNED: closed by input drift, because the specific thing to do is triage or a human,
      and both would be reading evidence the drift has already moved. Re-verifying is then the
      cheapest well-defined act, and forward scheduling does it."""
    out = []
    for rule in rules.FORWARD_PRIORITY:
        hit = _latest_fail(events, rule)
        if hit is None:
            continue
        idx, outcome = hit
        if not facts.verdict_trustworthy(module, events, rule, idx, outcome):
            continue
        att = _attribution(module, events, rule, outcome)
        if att["owner"]:
            if _answered(events, idx, att["owner"]):
                continue
        elif not facts.inputs_unchanged(module, rule, outcome):
            continue
        out.append({"rule": rule, "run": outcome["run"], **att})
    return out


def _escalation(c: dict) -> dict:
    """Why a complaint cannot be routed, derived from `(attribution, owner)` rather than
    raised where it was noticed — so the three namings and the unreliable diagnosis read as
    one classification instead of four scattered branches."""
    rule, named = c["rule"], c["attribution"]
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
        }
    if named is None:
        return {"rule": rule, "reason": f"{rule}: envelope named no fix_owner"}
    if named == rule:
        return {
            "rule": rule,
            "reason": f"{rule}: fix_owner is itself, in-stage remedy exhausted",
        }
    return {
        "rule": rule,
        "reason": f"{rule}: fix_owner {named!r} is outside its input closure",
    }


def _workdir_of(events, rule, run):
    for e in events:
        if e["type"] == "dispatch" and e["rule"] == rule and e["run"] == run:
            return e["workdir"]
    return None


def _antichain_ok(rule_name: str, inflight: list[dict]) -> bool:
    """The in-flight set must stay an ANTICHAIN in the input-closure order: no run may be
    open alongside another that (transitively) produces what it consumes, in either
    direction. One predicate for what used to be two unrelated half-guards:

    * downstream (a consumer is running) — the torn read Option C described: this rule's
      re-promote would land under the consumer's canonical read. That guard tested DIRECT
      consumers only, so a two-hop consumer (timing over rtl-design) slipped through.
    * upstream (a producer is running) — nothing guarded this at all. `rule_available` reads
      the producer's proof, which stays valid until the in-flight run reaps, so a consumer
      was admitted on inputs that were about to change and spent a full round on them.

    Pure, no I/O: the closure is a registry query."""
    for f in inflight:
        other = f["rule"]
        if other == rule_name:
            return False
        if other in rules.input_closure(rule_name):
            return False
        if rule_name in rules.input_closure(other):
            return False
    return True


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


def _group(open_):
    """Step 1: the open complaints, by who must act. `(repair, triage, unowned)`.

    A group-by, not a merge rule — which is the whole point: "co-failures naming one owner
    become one dispatch" cannot be implemented half-way if it is never implemented at all.

    An unowned complaint goes to the diagnostic its rule declares (`Rule.triage`) only when
    nothing has analysed this failure yet. An analysis that came back unreliable is a human's
    call, and re-running the same analyzer over the same evidence would only reproduce it."""
    repair: dict[str, list[dict]] = {}
    triage: dict[str, list[dict]] = {}
    unowned: list[dict] = []
    for c in open_:
        if c["owner"]:
            repair.setdefault(c["owner"], []).append(c)
            continue
        unowned.append(c)
        t = rules.RULES[c["rule"]].triage
        if t and not c["unreliable"]:
            triage.setdefault(t, []).append(c)
    return repair, triage, unowned


def _candidates(module, events, inflight, repair, triage, complained, work):
    """Every rule that could start right now, in the order they should be tried.

    Repairing and building are the same act — dispatch a rule, hand it the complaints it
    owns — so one set is ordered rather than two staged. Four filters, then three
    tie-breakers, each named where it is applied."""
    # Who is actually coming, for the advisory gate: a rule held out of the candidate set is
    # not going to speak this round, and an advisory hold that waits for it waits forever.
    # The gate's own premise (a predecessor that will never resolve must not hold anyone) is
    # what makes the subtraction load-bearing rather than cosmetic: an unroutable lint-cdc
    # failure otherwise pins synthesis behind a detector that is blocked on a human.
    coming = (work | set(repair) | set(triage)) - complained
    out = [
        r
        for r in coming
        if facts.rule_available(module, events, r)
        and _antichain_ok(r, inflight)
        and not _held_by_advisory(module, events, r, coming, inflight)
    ]
    # A candidate whose (transitive) producer is ALSO a candidate this round must wait for
    # it: its round would be built on inputs the other one is about to change. `_antichain_ok`
    # says the same thing about runs already open; this says it about the ones we are choosing
    # between, which the in-flight guard cannot see because the choice happens first. Without
    # it the tie-breakers below are free to pick a downstream owner (synthesis, `task`) ahead
    # of an upstream one (specification, `main-thread`) and spend that round twice.
    out = [
        r for r in out if not any(o != r and o in rules.input_closure(r) for o in out)
    ]
    return sorted(
        out,
        key=lambda r: (
            # answer a complaint before building anything: a proof with an unanswered
            # complaint is going to be re-verified either way, and doing it before the fix
            # lands spends the stage twice
            0 if (r in repair or r in triage) else 1,
            # a `task` executor returns immediately and a `main-thread` Skill() blocks the
            # turn, so starting the async one first is what makes the two overlap. Safe
            # because the filter above left only closure-minimal candidates: what remains is
            # an antichain, and reordering an antichain reorders nothing that had an order.
            0 if rules.RULES[r].execution == "task" else 1,
            rules.FORWARD_PRIORITY.index(r) if r in rules.FORWARD_PRIORITY else -1,
        ),
    )


def _dispatch_action(module, rule, repair, triage, unowned):
    """The DISPATCH, carrying everything this round is answerable for."""
    action = {
        "action": "DISPATCH",
        "rule": rule,
        "execution": rules.RULES[rule].execution,
    }
    if rule in repair:
        group = repair[rule]
        action["caused_by"] = [[c["rule"], c["run"]] for c in group]
        refs = [d["id"] for c in group for d in c["diagnoses"]]
        if refs:
            action["diagnosis_refs"] = refs
    elif rule in triage:
        action["params"] = {"sim_run": triage[rule][0]["run"]}
    if unowned:
        # The round keeps moving, but the human hears about the unroutable failures now
        # rather than after everything else has finished (§3.3: 无静默丢弃).
        action["escalations"] = [_escalation(c) for c in unowned]
    return _dispatched(module, action)


def _settle(module, events, inflight, required, unowned, closing):
    """Step 3: nothing can start. Say why, in the order that makes the reason true."""
    if inflight:
        return {"action": "YIELD", "in_flight": facts.in_flight(events)}
    if unowned:
        return {"action": "ESCALATE", **_escalation(unowned[0])}
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
    """Four steps, first one that can act wins. Each is one call, so the priority order —
    reap, then answer, then build, then settle — is the whole of the control flow."""
    events = facts.read_events(module)
    inflight = facts.in_flight(events)

    reap = _ready_to_reap(module, events, inflight, wake)
    if reap:
        return reap

    open_ = complaints(module, events)
    repair, triage, unowned = _group(open_)

    required = required_proofs(events)
    # A rule with an OPEN complaint does not run, in either role: re-verifying a proof whose
    # failure nobody has answered spends the stage to rediscover what is already written
    # down, and rebuilding a rule whose own failure is unattributed answers nothing.
    complained = {c["rule"] for c in open_}
    candidates = _candidates(
        module,
        events,
        inflight,
        repair,
        triage,
        complained,
        _forward_work(module, events, required),
    )
    if candidates:
        return _dispatch_action(module, candidates[0], repair, triage, unowned)

    return _settle(module, events, inflight, required, unowned, closing)
