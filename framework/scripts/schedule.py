"""VeriPower scheduler — objective -> exactly one action. Pure over (disk, ledger,
args): no state of its own. Composes route.py for self-describing-failure attribution.
Bare-importable (`import schedule`)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import facts  # noqa: E402
import route  # noqa: E402
import rules  # noqa: E402

_STAGE_PROOFS = [r for r in rules.FORWARD_PRIORITY]  # all 9 stage proofs, in order


def required_proofs(module: str, events: list[dict], objective: str) -> set[str]:
    if objective == "delivery":
        return set(_STAGE_PROOFS) - {"frontend-signoff"}
    if objective == "signoff":
        return set(_STAGE_PROOFS)
    if objective == "repair":
        # Scan newest-first: the first outcome seen per rule IS that rule's latest;
        # if it is a fail, that's the repair target. Position by scan order — never
        # events.index (duplicate event lines collide, and it's O(n) per call).
        seen_rules: set[str] = set()
        for e in reversed(events):
            if e["type"] == "outcome":
                if e["rule"] not in seen_rules:
                    if e["verdict"] == "fail":
                        return {e["rule"]}
                    seen_rules.add(e["rule"])
        return set()
    sys.exit(f"decide: unknown objective {objective!r}")


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
    """§3.4 fresh failure = the fail proof is fresh EXCEPT its verdict: recorded inputs
    match disk (condition 2), recorded outputs match disk (condition 4), oracle not
    reopened since (condition 3), AND every proof in the TRANSITIVE input closure is
    currently valid — closure has stale/missing = upstream still propagating, so the
    fail is STALE and goes to forward re-verify instead. Artifact edges only:
    sort_prereqs/ADVISORY_ORDER must NEVER appear in this path (spec §2)."""
    root = facts.module_root(module)
    proof = next((p for p in outcome["proofs"] if p["name"] == rule), None)
    if proof is None:
        return False
    # condition 2: own recorded inputs
    for path, recorded in proof.get("inputs", {}).items():
        if not facts.versions_match(
            recorded, facts.fingerprint_cached(root / path, root)
        ):
            return False
    # condition 4: own recorded outputs (hand-edited fail-run product = stale fail)
    for path, recorded in outcome.get("outputs", {}).items():
        if not facts.versions_match(
            recorded, facts.fingerprint_cached(root / path, root)
        ):
            return False
    # condition 3: oracle not reopened at/after this outcome's position
    r = rules.RULES[rule]
    if r.oracle and facts._reopened_after(events, proof["oracle"]["ref"], idx):
        return False
    # transitive input-closure proofs all valid (multi-hop propagation)
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
    all_fresh = every (rule, fail-outcome) fresh this round — used to merge every
    reliable attribution sharing the chosen fix_owner into ONE dispatch (§3.3:
    同 fix_owner 多条可靠归因合并注入同一 directive、逐条引用，无静默丢弃; the actual
    directive merge is the Orchestrator's job at directive-writing time, Task C9)."""
    diags = _active_diagnoses(events, rule, outcome)
    if diags:
        latest = diags[-1]
        if _reliable(latest):
            fix_owner = latest["fix_owner"]
            if not facts.rule_available(module, events, fix_owner):
                return {"action": "_defer_to_forward"}  # fix_owner inputs unavailable
            refs, fwd = [], False
            for frule, fout in all_fresh:
                for d in _active_diagnoses(events, frule, fout):
                    if _reliable(d) and d["fix_owner"] == fix_owner:
                        refs.append(d["id"])
                        fwd = fwd or d["source"] == "triage"  # verbatim forward (§3.4)
            return {
                "action": "DISPATCH",
                "rule": fix_owner,
                "execution": rules.RULES[fix_owner].execution,
                "needs_directive": True,
                "diagnosis_refs": refs,
                "triage_forward": fwd,
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
    # no ready diagnosis
    if rule == "simulation":  # ambiguous failure -> triage
        if any(f["rule"] == "simulation-triage" for f in facts.in_flight(events)):
            return {"action": "YIELD", "in_flight": _in_flight_view(module, events)}
        return {
            "action": "DISPATCH",
            "rule": "simulation-triage",
            "execution": "task",
            "params": {"sim_run": outcome["run"]},
        }
    # self-describing failure -> route inline (no diagnosis event)
    r = route.route(rule, **_route_kwargs(module, rule))
    if r["decision"] in (route.ESCALATE, route.NEED_INPUT):
        return {"action": "ESCALATE", "reason": r.get("reason_hint") or r["rule"]}
    target = r["decision"]
    if not facts.rule_available(module, events, target):
        return {"action": "_defer_to_forward"}
    return {
        "action": "DISPATCH",
        "rule": target,
        "execution": rules.RULES[target].execution,
        "needs_directive": True,
    }


def _route_kwargs(module: str, rule: str) -> dict:
    """Read the failed rule's canonical result.json stage_specific for route inputs."""
    p = facts.module_root(module) / Path(*rules.workdir_root(rule)) / "result.json"
    try:
        import json

        ss = json.loads(p.read_text()).get("stage_specific", {})
    except (OSError, ValueError):
        ss = {}
    return {
        "failure_kind": ss.get("failure_kind"),
        "failures": ss.get("failures"),
        "fail_reason": ss.get("fail_reason"),
    }


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


def _anchor_index(events: list[dict]) -> int | None:
    for i in range(len(events) - 1, -1, -1):
        if events[i]["type"] == "epoch":
            return i
    return None


def _reusable(module: str, events: list[dict], proof: str, conservative: bool) -> bool:
    if not facts.proof_valid(module, events, proof):
        return False
    if not conservative:
        return True
    anchor = _anchor_index(events)
    if anchor is None:
        # spec §3.6: 无 epoch 事件时报错"先开纪元"，不静默兜底 — a hard error, not an action.
        sys.exit(
            "decide --conservative: no epoch event; open an epoch first (kernel epoch)"
        )
    hit = facts._proof_outcome(events, proof)
    return hit is not None and hit[0] > anchor


def decide(
    module: str,
    *,
    wake: str | None = None,
    objective: str = "delivery",
    conservative: bool = False,
) -> dict:
    if objective == "signoff":
        conservative = True
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
            # public premise: target already in-flight -> do not double-dispatch
            if any(f["rule"] == disp["rule"] for f in inflight):
                return {"action": "YIELD", "in_flight": _in_flight_view(module, events)}
            return {**disp, "objective": objective, "conservative": conservative}
        else:
            return disp  # ESCALATE / YIELD

    # step 2: forward — missing/invalid required proofs, expanded to the REBUILD CLOSURE.
    # §3.3 末句: repair's rebuild chain (timing -> rebuild synthesis FIRST) walks the
    # producers of unavailable inputs; delivery's required set already spans the DAG so
    # the expansion is usually a no-op there.
    required = required_proofs(module, events, objective)
    work = {p for p in required if not _reusable(module, events, p, conservative)}
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
        if objective == "delivery":
            if not all(
                facts.proof_valid(module, events, rules.RULES[p].proof)
                for p in rules.sort_prereqs(rule)
                if rules.RULES[p].proof
            ):
                continue  # no overtaking — the ONLY consumer of sort_prereqs/advisory data
        candidates.append(rule)
    if candidates:
        rule = min(candidates, key=lambda r: rules.FORWARD_PRIORITY.index(r))
        if objective == "signoff" and rule == "frontend-signoff":
            gate = _signoff_gate(module, events)
            if gate is not None:
                return gate  # ESCALATE with the failing gate reason
        return {
            "action": "DISPATCH",
            "rule": rule,
            "execution": rules.RULES[rule].execution,
            "objective": objective,
            "conservative": conservative,
        }

    # step 3
    if inflight:
        return {"action": "YIELD", "in_flight": _in_flight_view(module, events)}
    if all(_reusable(module, events, p, conservative) for p in required):
        return {"action": "DONE"}
    return {
        "action": "ESCALATE",
        "reason": "no eligible rule, none in-flight, not done",
    }


def _signoff_gate(module: str, events: list[dict]) -> dict | None:
    """§3.6 signoff dispatchability: every other proof valid & post-anchor, oracle grade ∈
    {tool, human}, no unknown recorded version. Returns an ESCALATE action if the gate
    fails, else None. The no-epoch case never reaches here: decide with objective=signoff
    forces conservative, and _reusable already hard-errors '先开纪元' (spec §3.6 —
    报错不静默兜底, so it is an error, not an ESCALATE action). Iterates
    FORWARD_PRIORITY in order — a set here would make the ESCALATE reason vary with
    the hash seed when >1 proof fails the gate, breaching decide's purity invariant."""
    for proof in rules.FORWARD_PRIORITY:
        if proof == "frontend-signoff":
            continue
        if not _reusable(module, events, proof, True):
            return {
                "action": "ESCALATE",
                "reason": f"signoff blocked: {proof} not valid post-anchor",
            }
        _, outcome = facts._proof_outcome(events, proof)
        p = next(x for x in outcome["proofs"] if x["name"] == proof)
        if p["oracle"]["grade"] not in ("tool", "human"):
            return {
                "action": "ESCALATE",
                "reason": f"signoff blocked: {proof} oracle is proposed (pin it)",
            }
        if (
            facts.UNKNOWN in p.get("inputs", {}).values()
            or facts.UNKNOWN in outcome.get("outputs", {}).values()
        ):
            return {
                "action": "ESCALATE",
                "reason": f"signoff blocked: {proof} carries an unknown version",
            }
    return None
