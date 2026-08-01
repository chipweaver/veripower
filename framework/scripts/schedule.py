"""VeriPower scheduler — exactly one action per call. Pure over (disk, ledger, args): no
state of its own, and nothing the caller has to carry between turns. A self-describing
failure is attributed by its own envelope (`stage_specific.fix_owner`); this file only
checks that naming is legal. Bare-importable (`import schedule`)."""

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
    to re-verify and would crash step 2's FORWARD_PRIORITY.index (spec §2/§3.2).

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


def _fail_is_fresh(
    module: str, events: list[dict], rule: str, idx: int, outcome: dict
) -> bool:
    """§3.4 fresh failure = the fail proof is fresh EXCEPT its verdict, AND every proof in the
    TRANSITIVE input closure is currently valid — closure has stale/missing = upstream still
    propagating, so the fail is STALE and goes to forward re-verify instead.

    Conditions 2/3/4 are facts.proof_fresh_except_verdict, the same three the pass path uses;
    that is the point of asking there rather than here. Artifact edges only:
    ADVISORY_ORDER must NEVER appear in this path (spec §2)."""
    if not facts.proof_fresh_except_verdict(module, events, rule, idx, outcome):
        return False
    for upstream in rules.input_closure(rule):
        ur = rules.RULES[upstream]
        if ur.proof and not facts.proof_valid(module, events, ur.proof):
            return False
    return True


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
    """§3.4: reliable iff source=human (终审), OR confidence=high AND the attribution
    does not point at the failed rule's own judge. A diagnosis without fix_owner
    (self-pointing) can never auto-rebuild — there is no rebuild target."""
    if not diag.get("fix_owner"):
        return False
    if diag["source"] == "human":
        return True
    if diag.get("confidence") != "high":
        return False
    return diag["attribution"] != diag["subject"]["proof"]


def _disposition(
    module: str,
    events: list[dict],
    rule: str,
    outcome: dict,
    all_fresh: list[tuple[str, dict]],
) -> dict:
    """Action for one FRESH failure (§3.4): auto-rebuild / triage / escalate.
    all_fresh = every (rule, fail-outcome) fresh this round — used to merge every failure
    that routes to the chosen fix_owner into ONE dispatch (§3.3: 同 fix_owner 多条归因合并、
    逐条引用，无静默丢弃). The merge is a union of `caused_by` coordinates and
    `diagnosis_refs`, which the kernel resolves to paths at dispatch, so "no silent drop"
    is mechanical rather than an instruction to whoever writes the dispatch."""
    diags = _active_diagnoses(events, rule, outcome)
    if diags:
        latest = diags[-1]
        if _reliable(latest):
            fix_owner = latest["fix_owner"]
            if not facts.rule_available(module, events, fix_owner):
                return {"action": "_defer_to_forward"}  # fix_owner inputs unavailable
            refs, caused_by = [], []
            for frule, fout in all_fresh:
                for d in _active_diagnoses(events, frule, fout):
                    if _reliable(d) and d["fix_owner"] == fix_owner:
                        refs.append(d["id"])
                        coord = [frule, fout["run"]]
                        if coord not in caused_by:
                            caused_by.append(coord)
            return {
                "action": "DISPATCH",
                "rule": fix_owner,
                "execution": rules.RULES[fix_owner].execution,
                "diagnosis_refs": refs,
                "caused_by": caused_by,
            }
        # 现成归因但不可靠 (low confidence / self-pointing) -> 叫人, cited as candidates
        return {
            "action": "ESCALATE",
            "reason": f"unreliable diagnosis for {rule}",
            "candidates": [
                {
                    "attribution": d["attribution"],
                    "confidence": d.get("confidence"),
                    "diagnosis": d["id"],
                }
                for d in diags
            ],
        }
    # No ready diagnosis: the failing envelope names its own fix owner. The party that read
    # the raw tool output is the one that knows whose problem it is, so nothing re-derives
    # that from a classification.
    owner = _declared_owner(module, rule)
    if owner is None:
        # simulation is the one stage with a deeper analyzer behind it: a failure it looked
        # at and still could not attribute is what simulation-triage exists for. Everywhere else, an
        # envelope that names nobody is the stage saying it cannot tell — that is a human's
        # call, not a target to guess at.
        if rule == "simulation":
            if any(f["rule"] == "simulation-triage" for f in facts.in_flight(events)):
                return {"action": "YIELD", "in_flight": _in_flight_view(module, events)}
            return {
                "action": "DISPATCH",
                "rule": "simulation-triage",
                "execution": "task",
                "params": {"sim_run": outcome["run"]},
            }
        return {"action": "ESCALATE", "reason": f"{rule}: envelope named no fix_owner"}
    if owner == rule:
        # A defect the stage could fix from here is fixed WITHIN its run (rtl-design
        # re-dispatches a child, lint-cdc adds a waiver), so it never reaches this point as
        # a failure. Naming itself therefore means the in-stage remedy is exhausted; an
        # auto-rebuild would dispatch the failing rule at itself and loop.
        return {
            "action": "ESCALATE",
            "reason": f"{rule}: fix_owner is itself, in-stage remedy exhausted",
        }
    if owner not in rules.input_closure(rule):
        return {
            "action": "ESCALATE",
            "reason": f"{rule}: fix_owner {owner!r} is outside its input closure",
        }
    if not facts.rule_available(module, events, owner):
        return {"action": "_defer_to_forward"}
    # Merge every OTHER fresh failure that names this same owner, so one rework round answers
    # them together. Without it a co-failing stage is silently dropped and re-fails on the
    # next pass — the same 无静默丢弃 rule the diagnosis branch above obeys. A rule with an
    # active diagnosis is skipped: its own attribution decides its fix_owner.
    caused_by = [[rule, outcome["run"]]]
    for frule, fout in all_fresh:
        if frule == rule or _active_diagnoses(events, frule, fout):
            continue
        if _declared_owner(module, frule) == owner:
            caused_by.append([frule, fout["run"]])
    return {
        "action": "DISPATCH",
        "rule": owner,
        "execution": rules.RULES[owner].execution,
        "caused_by": caused_by,
    }


def _declared_owner(module: str, rule: str) -> str | None:
    """`stage_specific.fix_owner` from the failed rule's canonical result.json: the rule its
    own envelope says must act. None when the envelope names nobody (including an unreadable
    or absent envelope), which the caller reads as "this stage cannot tell". Legality is the
    caller's check, not this one's — this only reports what was written."""
    p = facts.module_root(module) / Path(*rules.workdir_root(rule)) / "result.json"
    try:
        ss = json.loads(p.read_text()).get("stage_specific", {})
    except (OSError, ValueError):
        return None
    owner = ss.get("fix_owner")
    return owner if owner in rules.RULES else None


def _in_flight_view(module: str, events: list[dict]) -> list[dict]:
    root = facts.module_root(module)
    out = []
    for f in facts.in_flight(events):
        wd = _workdir_of(events, f["rule"], f["run"])
        has = (root / wd / "result.json").exists() if wd else False
        out.append({"rule": f["rule"], "run": f["run"], "has_result": has})
    return out


def _workdir_of(events, rule, run):
    for e in events:
        if e["type"] == "dispatch" and e["rule"] == rule and e["run"] == run:
            return e["workdir"]
    return None


def _has_inflight_consumer(rule_name: str, inflight: list[dict]) -> bool:
    """Option C torn-read guard: True iff some in-flight run consumes rule_name's output
    (rule_name ∈ input_producers(that consumer)). Deferring rule_name's (re)dispatch means its
    new round never starts → no concurrent re-promote to tear the consumer's canonical read.
    Covers file- and dir-type tears; the consumer's next reap frees rule_name. Pure, no I/O."""
    return any(rule_name in rules.input_producers(f["rule"]) for f in inflight)


def _held_by_advisory(
    module: str,
    events: list[dict],
    rule: str,
    work: set[str],
    inflight: list[dict],
) -> bool:
    """No-overtake gate (§3.3): hold `rule` back while an `ADVISORY_ORDER` predecessor of it
    is not yet valid AND is going to speak — it is scheduled this round (`work`) or already
    running (`inflight`). The sole consumer of advisory data.

    An advisory edge is a bet that the cheap detector will answer before the expensive stage
    spends a run on inputs it is about to invalidate. The bet is only available while the
    detector is actually coming: a predecessor that is neither scheduled nor running will
    never resolve, so holding for it is waiting on nothing. That is not hypothetical — when
    the goal set narrows to one failing proof its advisory predecessor is not in the set, and
    a gate blind to that would hold the only candidate and leave the round with none.

    Asking who is coming, rather than which mode we are in, is also what makes the gate
    uniform. It reproduces the wide behaviour exactly (with nothing failing, every invalid
    proof is in `work`), and it fixes the case a mode-keyed gate got backwards: two stages
    joined by an advisory edge that fail together are both in `work`, so the cheap one runs
    first instead of racing the expensive one.

    Only ADVISORY_ORDER is read, never input_producers: `rule_available`, checked just above
    this, already implies every input producer's proof is valid, so the union the retired
    `sort_prereqs` computed had one half the caller had already established."""
    coming = work | {f["rule"] for f in inflight}
    for p in rules.ADVISORY_ORDER.get(rule, ()):
        if p in coming and not facts.proof_valid(module, events, rules.RULES[p].proof):
            return True
    return False


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


def decide(
    module: str,
    *,
    wake: str | None = None,
    closing: bool = False,
) -> dict:
    events = facts.read_events(module)
    inflight = facts.in_flight(events)

    # step 0: wake reap, then no-wake 收口 (completed run whose workdir has result.json)
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
    if ready:
        ready.sort(
            key=lambda f: (
                rules.FORWARD_PRIORITY.index(f["rule"])
                if f["rule"] in rules.FORWARD_PRIORITY
                else 99
            )
        )
        return {"action": "REAP", "rule": ready[0]["rule"], "run": ready[0]["run"]}

    # step 1: fresh-failure disposition, FORWARD_PRIORITY order, before forward
    fresh = []
    for rule in rules.FORWARD_PRIORITY:
        hit = _latest_fail(events, rule)
        if hit and _fail_is_fresh(module, events, rule, hit[0], hit[1]):
            fresh.append((rule, hit[1]))
    if fresh:
        rule, o = min(fresh, key=lambda t: rules.FORWARD_PRIORITY.index(t[0]))
        disp = _disposition(module, events, rule, o, fresh)
        if disp["action"] == "_defer_to_forward":
            pass  # fall through to step 2
        elif disp["action"] == "DISPATCH":
            # target already in-flight, OR its output has an in-flight consumer (Option C:
            # repair's fix_owner rebuild would re-promote under a background consumer's read)
            if any(
                f["rule"] == disp["rule"] for f in inflight
            ) or _has_inflight_consumer(disp["rule"], inflight):
                return {"action": "YIELD", "in_flight": _in_flight_view(module, events)}
            return _dispatched(module, disp)
        else:
            return disp  # ESCALATE / YIELD

    # step 2: forward — missing/invalid required proofs, expanded to the REBUILD CLOSURE.
    # §3.3 末句: a narrowed rebuild chain (timing -> rebuild synthesis FIRST) walks the
    # producers of unavailable inputs; when nothing is failing the required set already
    # spans the DAG, so the expansion is usually a no-op.
    required = required_proofs(events)
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
    candidates = []
    for rule in sorted(work, key=rules.FORWARD_PRIORITY.index):
        if any(f["rule"] == rule for f in inflight):
            continue
        if not facts.rule_available(module, events, rule):
            continue
        if _has_inflight_consumer(rule, inflight):  # Option C torn-read guard
            continue
        if _held_by_advisory(module, events, rule, work, inflight):
            continue
        candidates.append(rule)
    if candidates:
        rule = min(candidates, key=lambda r: rules.FORWARD_PRIORITY.index(r))
        return _dispatched(
            module,
            {
                "action": "DISPATCH",
                "rule": rule,
                "execution": rules.RULES[rule].execution,
            },
        )

    # step 3
    if inflight:
        return {"action": "YIELD", "in_flight": _in_flight_view(module, events)}
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
