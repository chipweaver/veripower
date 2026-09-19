"""Select the next action from current facts and unresolved repairs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import facts  # noqa: E402
import rules  # noqa: E402
import store  # noqa: E402

# Stage proofs in forward priority order.
_STAGE_PROOFS = [r for r in rules.FORWARD_PRIORITY if rules.RULES[r].proof]


def _latest_fail(events: list[dict], rule: str) -> tuple[int, dict] | None:
    """(position, outcome) of the rule's latest outcome iff it is a fail."""
    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        if e["type"] == "outcome" and e["rule"] == rule:
            return (i, e) if e["verdict"] == "fail" else None
    return None


def _active_diagnoses(events: list[dict], rule: str, outcome: dict) -> list[dict]:
    """Return unsuperseded diagnoses for this failure's run, in event order."""
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


def _legal(rule: str, name: str | None) -> bool:
    """A repair owner is the failed stage or one of its input producers."""
    return bool(name) and name in rules.repair_owners(rule)


def _event_index(events: list[dict], event: dict) -> int:
    """Find the position of this event object, including when equal-valued records coexist."""
    for i, e in enumerate(events):
        if e is event:
            return i
    return 0


def _oracle_retracted(events: list[dict], rule: str, outcome: dict) -> bool:
    """Return whether the run's oracle was reopened after dispatch and has no live pin."""
    proof = next((p for p in outcome["proofs"] if p["name"] == rule), None)
    if proof is None or not rules.RULES[rule].oracle:
        return False
    oref = proof["oracle"]["ref"]
    d_idx = facts.dispatch_index(events, rule, outcome["run"])
    anchor = d_idx if d_idx is not None else 0
    return facts.oracle_reopened_after(events, oref, anchor) and not facts.live_pins(
        events, oref
    )


def _owner(module: str, events: list[dict], rule: str, idx: int, outcome: dict) -> dict:
    """Resolve repair owners from diagnoses, the stage's result, then its diagnostic rule.

    Reopened oracles cannot direct repairs. An unresolved diagnosis holds the
    whole failure for clarification; otherwise group diagnoses by owner and
    record when each attribution became known."""
    if _oracle_retracted(events, rule, outcome):
        return {
            "attribution": None,
            "owners": [],
            "unroutable": [],
            "retracted": True,
        }
    base = {"retracted": False}
    diags = _active_diagnoses(events, rule, outcome)
    if diags:  # source 1: a later analysis outranks the stage's own self-report
        if not all(d.get("fix_owner") for d in diags):
            return {
                **base,
                "attribution": diags[-1]["attribution"],
                "owners": [],
                "unroutable": diags,
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
            "unroutable": [],
        }
    named = facts.declared_fix_owner(
        module, rule
    )  # source 2: the failing stage's own envelope
    if named:
        return {
            **base,
            "attribution": named,
            "owners": (
                [{"owner": named, "since": idx, "diagnoses": []}]
                if _legal(rule, named)
                else []
            ),
            "unroutable": [],
        }
    # source 3: nobody named anyone, so the stage's declared diagnostic must find out
    triage = rules.RULES[rule].triage
    return {
        **base,
        "attribution": None,
        "owners": [{"owner": triage, "since": idx, "diagnoses": []}] if triage else [],
        "unroutable": [],
    }


def _answered(events: list[dict], since: int, owner: str) -> bool:
    """A later owner dispatch answers an attribution unless its outcome is blocked."""
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
    """List the latest failed stage outcomes and their repair owners, in forward priority order."""
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
    """Return unresolved failure-owner pairs after excluding owners that have acted."""
    out = []
    for f in fails:
        rest = {k: v for k, v in f.items() if k != "owners"}
        for o in f["owners"]:
            if not _answered(events, o["since"], o["owner"]):
                out.append({**rest, **o})
    return out


def _escalation(c: dict) -> dict:
    """Describe why the failure cannot be assigned an automatic repair."""
    rule, named = c["rule"], c["attribution"]
    if c.get("retracted"):
        return {
            "rule": rule,
            "reason": f"{rule}: the oracle that judged this failure was reopened",
        }
    if c["unroutable"]:
        return {
            "rule": rule,
            "reason": f"{rule}: diagnosis named no fix_owner",
            "candidates": [
                {
                    "attribution": d["attribution"],
                    "diagnosis": d["id"],
                    # present on the entries that DID name someone: they are held with the
                    # rest, and the decision maker needs to see what was already attributed.
                    **({"fix_owner": d["fix_owner"]} if d.get("fix_owner") else {}),
                }
                for d in c["unroutable"]
            ],
        }
    if named is None:
        return {"rule": rule, "reason": f"{rule}: envelope named no fix_owner"}
    return {
        "rule": rule,
        "reason": f"{rule}: fix_owner {named!r} is neither itself nor an input producer",
    }


def _unblocked(rule_name: str, pending: set[str], inflight: list[dict]) -> bool:
    """Check producer and consumer dependencies before starting a rule.

    An in-flight producer or consumer blocks the rule. A producer that is only a
    candidate blocks proof-producing work; diagnostics can analyze a past run."""
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
    """Hold a rule for an invalid advisory predecessor that is scheduled or running."""
    coming = coming | {f["rule"] for f in inflight}
    for p in rules.ADVISORY_ORDER.get(rule, ()):
        if p in coming and not facts.proof_valid(module, events, rules.RULES[p].proof):
            return True
    return False


def _forward_work(module: str, events: list[dict], required: set[str]) -> set[str]:
    """Expand invalid required proofs with producers needed to make their inputs available."""
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
    """Add the exact dispatch argv for the selected action and its repair context."""
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
    """Select a run with a result, or the exited executor identified by --wake."""
    if wake and ":" in wake:
        r, _, n = wake.partition(":")
        if n.isdigit() and {"rule": r, "run": int(n)} in inflight:
            return {"action": "REAP", "rule": r, "run": int(n)}
    ready = [
        f
        for f in inflight
        if (
            store.module_root(module)
            / (facts.run_workdir(events, f["rule"], f["run"]) or "")
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
    """Group outstanding failures by repair owner for a shared dispatch."""
    out: dict[str, list[dict]] = {}
    for f in owed_:
        out.setdefault(f["owner"], []).append(f)
    return out


def _candidates(module, events, inflight, repair, owed_rules, work):
    """Order currently startable rules by repair, execution mode and forward priority."""
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
            # Start independent background tasks before main-thread work.
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
    """Return YIELD, DONE or the remaining blocker when no rule can start."""
    if inflight:
        return {"action": "YIELD", "in_flight": facts.in_flight(events)}
    if all(facts.proof_valid(module, events, p) for p in required):
        if closing:
            # Closing also checks signoff readiness.
            reason = facts.signoff_gate(module, events)
            if reason is not None:
                return {"action": "ESCALATE", "reason": reason}
            # "go stamp" is where the authorized decision is made; hand them the proposition, not just
            # the permission (facts.signoff_basis).
            return {"action": "DONE", "basis": facts.signoff_basis(module, events)}
        return {"action": "DONE"}
    # The producer graph terminates at the intent document.
    return {
        "action": "ESCALATE",
        "reason": f"intent tree incomplete: {rules.INTENT_DOC} is not there, "
        "and no stage produces it",
    }


def decide(
    module: str,
    *,
    wake: str | None = None,
    closing: bool = False,
) -> dict:
    """Four steps, first one that can act wins."""
    events = store.read_events(module)
    inflight = facts.in_flight(events)

    reap = _ready_to_reap(module, events, inflight, wake)
    if reap:
        return reap

    fails = _failures(module, events)
    unclear = [f for f in fails if not f["owners"]]
    if unclear:
        # Clarify unresolved attribution before scheduling repairs.
        return {"action": "ESCALATE", **_escalation(unclear[0])}
    # ↓ every failure below this line has an owner
    owed_ = owed(events, fails)

    repair = _group(owed_)
    # Wait for upstream repairs before re-verifying, but allow a stage to repair itself.
    owed_rules = {f["rule"] for f in owed_ if f["owner"] != f["rule"]}
    required = set(_STAGE_PROOFS)
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
