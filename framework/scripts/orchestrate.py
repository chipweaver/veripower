#!/usr/bin/env python3
"""VeriPower orchestration decider — the deterministic control loop.

`orchestrate.py decide` reads on-disk state and returns EXACTLY ONE next action
for the design-flow Orchestrator to execute. Decision-support only: it reads
state and decides; it never mutates (state.py owns mutations). Composes the
pure deciders route() / eligible(). Reproduces ARCHITECTURE.md
§5's loop as tested code. The LLM loops on `decide` until YIELD/DONE/ESCALATE.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from route import _inputs_from_result_json, route
from state import read_events, read_task
from topology import FORWARD_PRIORITY, _result_path, eligible

MAIN_THREAD = {"specification", "simulation-plan", "rtl-design", "simulation"}
_PPA_DIMS = {
    "synthesis": {"area_um2", "timing_slack_ns"},
    "power-analysis": {"power_mw"},
}


def _ppa_targets(module: str, stage: str) -> list:
    if stage not in _PPA_DIMS:
        return []
    p = _result_path(module, "specification")
    if not p.exists():
        return []
    try:
        spec = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    dims = _PPA_DIMS[stage]
    return [
        t
        for t in spec.get("stage_specific", {}).get("ppa_targets", [])
        if t.get("dim") in dims
    ]


def _triage_pending(events: list) -> bool:
    """True if a triage was dispatched and not yet resolved: a debug_dispatch
    event later than the most recent simulation outcome event."""
    last_outcome = last_dispatch = -1
    for i, e in enumerate(events):
        if e.get("type") == "outcome" and e.get("stage") == "simulation":
            last_outcome = i
        elif e.get("type") == "debug_dispatch":
            last_dispatch = i
    return last_dispatch > last_outcome


def _promote_failed_count(events: list, stage: str, run: int) -> int:
    return sum(
        1
        for e in events
        if e.get("type") == "outcome"
        and e.get("stage") == stage
        and e.get("run") == run
        and e.get("result_status") == "promote_failed"
    )


def _handle_failure(
    module: str,
    failed: str,
    events: list,
    analysis: dict | None,
    failed_run: int | None = None,
) -> dict:
    kwargs: dict = {}
    if failed == "simulation":
        if analysis is None:
            if _triage_pending(events):
                # triage Task is async (not a pipeline stage); wait for the ANALYSIS wake.
                return {
                    "action": "YIELD",
                    "in_flight": [],
                    "waiting_on": "simulation-triage",
                }
            return {"action": "DISPATCH_TRIAGE", "sim_run": failed_run}
        kwargs["root_cause"] = analysis.get("root_cause")
        kwargs["analysis_state"] = analysis.get("analysis_state")
        kwargs["confidence"] = analysis.get("confidence")
    else:
        rj = _result_path(module, failed)
        if rj.exists():
            kwargs.update(_inputs_from_result_json(str(rj)))
    r = route(failed, **kwargs)
    if r["decision"] == "ESCALATE":
        return {"action": "ESCALATE", "reason": r.get("reason_hint") or r["rule"]}
    if r["decision"] == "NEED_INPUT":
        return {"action": "DISPATCH_TRIAGE", "sim_run": failed_run}
    return {
        "action": "REWORK",
        "failed_stage": failed,
        "target_stage": r["decision"],
        "reason_hint": r.get("reason_hint") or r["rule"],
    }


def decide(module: str, wake: str | None = None, analysis: dict | None = None) -> dict:
    task = read_task(module)
    stages = task["stages"]
    events = read_events(module)

    # 0. promote_failed retry/escalate (deterministic single-retry cap).
    for s in FORWARD_PRIORITY:
        for rf in stages[s]["in_flight"]:
            pf = _promote_failed_count(events, s, rf["run"])
            if pf == 1:
                return {"action": "REAP", "stage": s, "run": rf["run"]}  # single retry
            if pf >= 2:
                return {
                    "action": "ESCALATE",
                    "reason": f"promote_failed persistent for {s} run {rf['run']}",
                }

    # 1. Wake-turn reap: --wake S:N names a completed in_flight run.
    # --wake is LLM-formatted (least-trusted input); a malformed/stale wake
    # (no colon, non-numeric run, unknown stage, or run not in_flight) falls
    # through to the normal decision — same no-op semantics as a stale wake.
    if wake and ":" in wake:
        s, _, n = wake.partition(":")
        if (
            n.isdigit()
            and s in stages
            and any(rf["run"] == int(n) for rf in stages[s]["in_flight"])
        ):
            return {"action": "REAP", "stage": s, "run": int(n)}

    # 2. Terminate.
    fs = stages["frontend-signoff"]
    if fs["status"] == "pass" and fs["freshness"] == "clean":
        return {"action": "DONE"}

    # 3. First failure (one at a time, FORWARD_PRIORITY order).
    for s in FORWARD_PRIORITY:
        st = stages[s]
        if st["status"] == "fail" and st["freshness"] == "clean":
            return _handle_failure(module, s, events, analysis, st.get("current_run"))

    # 4. Forward dispatch: first eligible by priority.
    for s in FORWARD_PRIORITY:
        if eligible(s, task):
            kind = "main-thread" if s in MAIN_THREAD else "task"
            return {
                "action": "DISPATCH",
                "stage": s,
                "kind": kind,
                "ppa_targets": _ppa_targets(module, s),
            }

    # 5. Yield (something running) or escalate (stuck).
    in_flight = [
        [s, rf["run"]] for s in FORWARD_PRIORITY for rf in stages[s]["in_flight"]
    ]
    if in_flight:
        return {"action": "YIELD", "in_flight": in_flight}
    return {
        "action": "ESCALATE",
        "reason": "no eligible stage, none in-flight, pipeline not done",
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="orchestrate.py")
    sub = ap.add_subparsers(dest="command")
    p = sub.add_parser(
        "decide", help="Return the single orchestrator action to take now."
    )
    p.add_argument("--module", required=True)
    p.add_argument(
        "--wake", default=None, help="<stage>:<run> from the task-notification"
    )
    p.add_argument(
        "--analysis",
        default=None,
        help="'-' stdin, or path to the landed analysis.json",
    )
    args = ap.parse_args()
    if args.command != "decide":
        ap.print_help()
        sys.exit(1)
    if args.analysis == "-":
        analysis = json.loads(sys.stdin.read())
    elif args.analysis:
        try:
            analysis = json.loads(Path(args.analysis).read_text())
        except (OSError, json.JSONDecodeError):
            analysis = None  # missing/partial landed file → analysis=None; with a triage already dispatched this YIELDs to await the async triage notification (not a re-dispatch)
    else:
        analysis = None
    print(json.dumps(decide(args.module, wake=args.wake, analysis=analysis), indent=2))


if __name__ == "__main__":
    main()
