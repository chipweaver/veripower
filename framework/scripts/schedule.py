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
STAGE_PROOFS = [r for r in rules.FORWARD_PRIORITY if rules.RULES[r].proof]


def active_diagnoses(events: list[dict], rule: str, outcome: dict) -> list[dict]:
    """Return unsuperseded diagnoses for this failure's run, in event order."""
    superseded_ids = {
        event["supersedes"]
        for event in events
        if event["type"] == "diagnosis" and event.get("supersedes")
    }
    return [
        event
        for event in events
        if event["type"] == "diagnosis"
        and event["id"] not in superseded_ids
        and event["subject"]["proof"] == rule
        and event["subject"]["outcome_run"] == outcome["run"]
    ]


def resolve_repair_owners(
    module: str, events: list[dict], rule: str, failure_index: int, outcome: dict
) -> dict:
    """Resolve repair owners from diagnoses, the stage's result, then its diagnostic rule.

    An unresolved diagnosis holds the failure for clarification; otherwise group
    diagnoses by owner and record when each attribution became known."""
    diagnoses = active_diagnoses(events, rule, outcome)
    if diagnoses:  # source 1: a later analysis outranks the stage's own self-report
        if not all(diagnosis.get("fix_owner") for diagnosis in diagnoses):
            return {
                "attribution": diagnoses[-1].get("attribution"),
                "owners": [],
                "unroutable": diagnoses,
            }
        owners = {}
        for diagnosis in diagnoses:
            owner_state = owners.setdefault(
                diagnosis["fix_owner"],
                {
                    "owner": diagnosis["fix_owner"],
                    "since": failure_index,
                    "diagnoses": [],
                },
            )
            owner_state["since"] = max(
                owner_state["since"],
                next(index for index, event in enumerate(events) if event is diagnosis),
            )
            owner_state["diagnoses"].append(diagnosis)
        return {
            "attribution": diagnoses[-1].get("attribution"),
            "owners": sorted(
                owners.values(), key=lambda owner_state: owner_state["since"]
            ),
            "unroutable": [],
        }
    declared_owner = facts.declared_fix_owner(
        module, rule
    )  # source 2: the failing stage's own envelope
    if declared_owner:
        return {
            "attribution": declared_owner,
            "owners": (
                [{"owner": declared_owner, "since": failure_index, "diagnoses": []}]
                if declared_owner in rules.repair_owners(rule)
                else []
            ),
            "unroutable": [],
        }
    # source 3: nobody named anyone, so the stage's declared diagnostic must find out
    triage = rules.RULES[rule].triage
    return {
        "attribution": None,
        "owners": [{"owner": triage, "since": failure_index, "diagnoses": []}]
        if triage
        else [],
        "unroutable": [],
    }


def repair_started(events: list[dict], since: int, owner: str) -> bool:
    """A later owner dispatch answers an attribution unless its outcome is blocked."""
    for index, event in enumerate(events):
        if index <= since or event["type"] != "dispatch" or event["rule"] != owner:
            continue
        completion = next(
            (
                outcome
                for outcome in events[index + 1 :]
                if outcome["type"] == "outcome"
                and outcome["rule"] == owner
                and outcome["run"] == event["run"]
            ),
            None,
        )
        if completion is None or completion["verdict"] != "blocked":
            return True
    return False


def failures(module: str, events: list[dict]) -> list[dict]:
    """List the latest failed stage outcomes and their repair owners, in forward priority order."""
    out = []
    for rule in rules.FORWARD_PRIORITY:
        latest_failure = next(
            (
                (index, event)
                for index, event in reversed(list(enumerate(events)))
                if event["type"] == "outcome" and event["rule"] == rule
            ),
            None,
        )
        if latest_failure is None or latest_failure[1]["verdict"] != "fail":
            continue
        outcome_index, outcome = latest_failure
        out.append(
            {
                "rule": rule,
                "run": outcome["run"],
                "idx": outcome_index,
                **resolve_repair_owners(module, events, rule, outcome_index, outcome),
            }
        )
    return out


def owed(events: list[dict], fails: list[dict]) -> list[dict]:
    """Return unresolved failure-owner pairs after excluding owners that have acted."""
    out = []
    for failure in fails:
        failure_context = {k: v for k, v in failure.items() if k != "owners"}
        for owner_state in failure["owners"]:
            if not repair_started(events, owner_state["since"], owner_state["owner"]):
                out.append({**failure_context, **owner_state})
    return out


def escalation(failure: dict) -> dict:
    """Describe why the failure cannot be assigned an automatic repair."""
    rule, attribution = failure["rule"], failure["attribution"]
    if failure["unroutable"]:
        return {
            "rule": rule,
            "reason": f"{rule}: diagnosis named no fix_owner",
            "candidates": [
                {
                    "diagnosis": diagnosis["id"],
                    **{
                        key: diagnosis[key]
                        for key in ("attribution", "fix_owner", "reason")
                        if key in diagnosis
                    },
                }
                for diagnosis in failure["unroutable"]
            ],
        }
    if attribution is None:
        return {"rule": rule, "reason": f"{rule}: envelope named no fix_owner"}
    return {
        "rule": rule,
        "reason": f"{rule}: fix_owner {attribution!r} is neither itself nor an input producer",
    }


def dependencies_ready(rule_name: str, pending: set[str], inflight: list[dict]) -> bool:
    """Check producer and consumer dependencies before starting a rule.

    An in-flight producer or consumer blocks the rule. A producer that is only a
    candidate blocks proof-producing work; diagnostics can analyze a past run."""
    closure = rules.input_closure(rule_name)
    running = {execution["rule"] for execution in inflight}
    if any(stage_name in closure for stage_name in running):
        return False
    if rules.RULES[rule_name].proof and any(
        producer != rule_name and producer in closure for producer in pending - running
    ):
        return False
    return not any(
        rule_name in rules.input_closure(stage_name) for stage_name in running
    )


def held_by_advisory(
    module: str,
    events: list[dict],
    rule: str,
    coming: set[str],
    inflight: list[dict],
) -> bool:
    """Hold a rule for an invalid advisory predecessor that is scheduled or running."""
    coming = coming | {execution["rule"] for execution in inflight}
    for predecessor in rules.ADVISORY_ORDER.get(rule, ()):
        if predecessor in coming and not facts.proof_valid(
            module, events, rules.RULES[predecessor].proof
        ):
            return True
    return False


def forward_work(module: str, events: list[dict], required: set[str]) -> set[str]:
    """Expand invalid required proofs with producers needed to make their inputs available."""
    work = {
        stage_name
        for stage_name in required
        if not facts.proof_valid(module, events, stage_name)
    }
    frontier = set(work)
    while frontier:
        next_frontier = set()
        for rule in frontier:
            if facts.rule_available(module, events, rule):
                continue
            for producer in rules.input_producers(rule):
                producer_rule = rules.RULES[producer]
                needs = (
                    producer_rule.proof
                    and not facts.proof_valid(module, events, producer_rule.proof)
                ) or not facts.rule_available(module, events, producer)
                if needs and producer not in work:
                    work.add(producer)
                    next_frontier.add(producer)
        frontier = next_frontier
    return work


def ready_to_reap(module, events, inflight, wake):
    """Select a run with a result, or the exited executor identified by --wake."""
    if wake and ":" in wake:
        stage_name, unused, run_number = wake.partition(":")
        if (
            run_number.isdigit()
            and {"rule": stage_name, "run": int(run_number)} in inflight
        ):
            return {"action": "REAP", "rule": stage_name, "run": int(run_number)}
    ready = [
        execution
        for execution in inflight
        if (
            Path(module)
            / (facts.run_workdir(events, execution["rule"], execution["run"]) or "")
            / "result.json"
        ).is_file()
    ]
    if not ready:
        return None
    ready.sort(
        key=lambda execution: (
            rules.FORWARD_PRIORITY.index(execution["rule"])
            if execution["rule"] in rules.FORWARD_PRIORITY
            else 99
        )
    )
    return {"action": "REAP", "rule": ready[0]["rule"], "run": ready[0]["run"]}


def ready_stages(module, events, inflight, repair, owed_rules, work):
    """Order currently startable rules by repair, execution mode and forward priority."""
    pool = (
        (work | set(repair))
        - owed_rules
        - {execution["rule"] for execution in inflight}
    )
    # `coming`, for the advisory gate: a rule held out of the pool is not going to speak
    # this round, and an advisory hold that waits for it waits forever.
    startable = [
        stage_name
        for stage_name in pool
        if facts.rule_available(module, events, stage_name)
        and not held_by_advisory(module, events, stage_name, pool, inflight)
    ]
    pending = {execution["rule"] for execution in inflight} | set(startable)
    available_stages = [
        stage_name
        for stage_name in startable
        if dependencies_ready(stage_name, pending, inflight)
    ]
    return sorted(
        available_stages,
        key=lambda stage_name: (
            # answer a failure before building anything: a proof still owed against is going
            # to be re-verified either way, and doing it before the fix lands spends it twice
            0 if stage_name in repair else 1,
            # Start independent background tasks before main-thread work.
            0 if rules.RULES[stage_name].execution == "task" else 1,
            rules.FORWARD_PRIORITY.index(stage_name)
            if stage_name in rules.FORWARD_PRIORITY
            else -1,
        ),
    )


def dispatch_action(module, rule, repair):
    """The DISPATCH, carrying every failure this round is answerable for."""
    action = {
        "action": "DISPATCH",
        "rule": rule,
        "execution": rules.RULES[rule].execution,
    }
    group = repair.get(rule, [])
    if group:
        action["caused_by"] = [[failure["rule"], failure["run"]] for failure in group]
        diagnosis_ids = [
            diagnosis["id"] for failure in group for diagnosis in failure["diagnoses"]
        ]
        if diagnosis_ids:
            action["diagnosis_refs"] = diagnosis_ids
        # A rule that declares params is being dispatched AT one of these failures — today
        # only the diagnostic, which needs the run it must open.
        if "sim_run" in rules.RULES[rule].params:
            action["params"] = {"sim_run": group[0]["run"]}
    arguments = ["dispatch", "--module", module, "--rule", rule]
    for failed_rule, failed_run in action.get("caused_by", []):
        arguments += ["--caused-by", f"{failed_rule}:{failed_run}"]
    if action.get("diagnosis_refs"):
        arguments += ["--diagnosis-refs", ",".join(action["diagnosis_refs"])]
    if action.get("params"):
        arguments += ["--params", json.dumps(action["params"], sort_keys=True)]
    action["dispatch_args"] = arguments
    return action


def settle(module, events, inflight, required, closing):
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
            return {"action": "DONE", "basis": facts.signoff_basis(events)}
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

    reap = ready_to_reap(module, events, inflight, wake)
    if reap:
        return reap

    failed_stages = failures(module, events)
    unclear = [failure for failure in failed_stages if not failure["owners"]]
    if unclear:
        # Clarify unresolved attribution before scheduling repairs.
        return {"action": "ESCALATE", **escalation(unclear[0])}
    # ↓ every failure below this line has an owner
    pending_repairs = owed(events, failed_stages)

    repair: dict[str, list[dict]] = {}
    for failure in pending_repairs:
        repair.setdefault(failure["owner"], []).append(failure)
    # Wait for upstream repairs before re-verifying, but allow a stage to repair itself.
    owed_rules = {
        failure["rule"]
        for failure in pending_repairs
        if failure["owner"] != failure["rule"]
    }
    required = set(STAGE_PROOFS)
    candidates = ready_stages(
        module,
        events,
        inflight,
        repair,
        owed_rules,
        forward_work(module, events, required),
    )
    if candidates:
        return dispatch_action(module, candidates[0], repair)

    return settle(module, events, inflight, required, closing)
