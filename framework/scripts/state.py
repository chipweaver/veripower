#!/usr/bin/env python3
"""VeriPower orchestration — state tool.

Single-file CLI. 8 commands: init, status, start, complete, rework, invalidate-stage,
convergence, log. No routing logic — all decisions belong to
Orchestrator agent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# ── DAG topology (single source of truth: topology.py) ──────────
# Re-exported so existing `state.X` references (verify.py:23 + ~118 test
# refs + state.py's own internal uses) keep resolving — do NOT rewrite
# call sites to topology.X.
# Ensure framework/scripts/ is on sys.path so the bare `topology` import
# succeeds whether state.py is loaded directly or via the framework.scripts
# namespace package (e.g. `from framework.scripts import state` in pytest).
# Always import topology the BARE way (`import topology` / `from topology import`).
# Never `from framework.scripts.topology import ...` — that creates a SECOND module
# object, so `framework.scripts.topology.X is topology.X` is False, silently breaking
# the `state.X is topology.X` identity this re-export guarantees.
sys.path.insert(0, str(Path(__file__).parent))
# ── Artifact lifecycle (single source of truth: artifacts.py) ───
# Re-exported so existing `state.promote` / `state._mirror_subagent_trace` /
# `state.repair_partial_promote_if_needed` references keep resolving — same
# pattern as the topology re-export above.
from artifacts import (  # noqa: E402
    _mirror_subagent_trace,
    promote,
    repair_partial_promote_if_needed,
)
from topology import (
    FORWARD_PRIORITY,
    PREREQ_OF,
    SKILL_OF,
    _result_path,
    descendants,
    is_dag_ancestor,
)

# ── File paths ─────────────────────────────────────────────────


def _task_path(module: str) -> Path:
    return Path("asic") / module / "task.json"


def _events_path(module: str) -> Path:
    return Path("asic") / module / "events.jsonl"


# ── Timestamps ─────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ── reason validation ─────────────────────────────────────────────


def _validate_reason(s: str | None) -> str | None:
    """Return error message, or None if reason is acceptable.

    Used at the CLI input layer for commands where --reason is provided directly
    by the operator/Orchestrator: cmd_rework and cmd_complete (blocked branch). The
    purpose is fail-fast with a clear message ('--reason: reason must be
    non-empty') before constructing the event body.

    Note: cmd_log (escalation) does NOT call this — `escalation.schema.json`
    enforces the same rule via `pattern: ".*\\\\S.*"`, and append_event runs
    that schema check single-pointedly. Internally-emitted reasons (e.g.
    cmd_complete's discarded/invalid/promote_failed branches) are likewise
    non-empty by construction.
    """
    if s is None or not s.strip():
        return "reason must be non-empty (after strip)"
    return None


# ── task.json I/O ──────────────────────────────────────────────


def _blank_task(module: str) -> dict:
    return {
        "module": module,
        "stages": {
            s: {
                "status": "not_started",
                "freshness": "clean",
                "current_run": None,
                "in_flight": [],
            }
            for s in FORWARD_PRIORITY
        },
    }


def read_task(module: str) -> dict:
    p = _task_path(module)
    if not p.exists():
        sys.exit(
            f"Module not initialized: {p} not found. Run: state.py init --module {module}"
        )
    return json.loads(p.read_text())


def write_task(module: str, task: dict) -> None:
    p = _task_path(module)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(p)


# ── events.jsonl I/O ───────────────────────────────────────────


# append_event is the SINGLE point of event schema validation.
# A SystemExit raised here indicates a state.py self-bug (malformed event
# constructed by cmd_start / cmd_complete / cmd_rework). When this happens
# AFTER a sibling write_task in those commands, task.json is left ahead of
# events.jsonl — the next replay must reconcile by treating events as
# authoritative and rebuilding task.json from event history.
def append_event(module: str, event: dict, ts: str | None = None) -> None:
    event = {"ts": ts or _now_iso(), **event}
    valid, err = _validate_event(event)
    if not valid:
        sys.exit(f"event schema violation: {err}")
    p = _events_path(module)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(module: str) -> list[dict]:
    p = _events_path(module)
    if not p.exists():
        return []
    events = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # tolerate truncated last line
    return events


# ── cascade-stale ──────────────────────────────────────────────


def _compute_cascade(task: dict, source: str) -> list[dict]:
    """Mark downstream pass/fail/in_progress stages stale (in-memory).
    Traversal order is topology.descendants() (BFS) so `staled` is stable."""
    staled: list[dict] = []
    for s in descendants(source):
        st = task["stages"][s]
        if (
            st["status"] in ("pass", "fail", "in_progress")
            and st["freshness"] != "stale"
        ):
            st["freshness"] = "stale"
            staled.append({"stage": s})
    return staled


# ── Commands ───────────────────────────────────────────────────


def cmd_init(module: str) -> dict:
    p = _task_path(module)
    if p.exists():
        return {"ok": True, "created": False}
    p.parent.mkdir(parents=True, exist_ok=True)
    write_task(module, _blank_task(module))
    return {"ok": True, "created": True}


def cmd_status(module: str) -> dict:
    task = read_task(module)
    return {
        "module": task["module"],
        "stages": task["stages"],
    }


def cmd_start(
    module: str, stage: str, *, orchestrator_context_source: str | None = None
) -> dict:
    repair_partial_promote_if_needed(module, stage)
    task = read_task(module)
    st = task["stages"][stage]

    # Reject if in_progress/clean (already running, no re-dispatch)
    if st["status"] == "in_progress" and st["freshness"] == "clean":
        return {"ok": False, "error": f"stage {stage} is already in_progress/clean"}

    # Determine mode + eligibility
    if st["freshness"] == "stale":
        mode = "rework"
    elif st["status"] == "not_started" and st["freshness"] == "clean":
        mode = "forward"
    elif st["status"] == "in_progress" and st["freshness"] == "stale":
        # cascade hit a running stage; allow new run alongside old
        mode = "rework"
    else:
        return {
            "ok": False,
            "error": f"stage {stage} is {st['status']}/{st['freshness']} — not eligible for start",
        }

    # Validate prerequisites (must all be pass/clean)
    for prereq in PREREQ_OF[stage]:
        pst = task["stages"][prereq]
        if pst["status"] != "pass" or pst["freshness"] != "clean":
            return {
                "ok": False,
                "error": f"prerequisite {prereq} is {pst['status']}/{pst['freshness']}",
            }

    # Resolve rework_trigger BEFORE event append (avoid scanning own dispatch)
    trigger = None
    if mode == "rework":
        trigger = _find_rework_trigger(module, stage)

    # Compute new run + workdir
    new_run = (st["current_run"] or 0) + 1
    module_root = Path("asic") / module
    workdir_path = _result_path(module, stage).parent / "runs" / str(new_run)
    workdir_rel = str(workdir_path) + "/"
    workdir_path.mkdir(parents=True, exist_ok=True)

    # === three-stage: compute → events first → state after ===
    # orchestrator_context: per-dispatch ephemeral hint channel.
    # Orchestrator passes content (already extracted from --orchestrator-context FILE/-
    # in the CLI layer); state.py code-writes a sibling file in the run workdir
    # and returns the relative path. Not promoted to canonical.
    # File-write happens in the compute phase BEFORE events-first/state-after so that an
    # OSError (disk full, permissions) propagates out of cmd_start before any
    # persistent state is mutated — cleanest failure mode.
    orchestrator_context_rel: str | None = None
    if orchestrator_context_source is not None:
        ctx_path = workdir_path / "orchestrator-context.md"
        ctx_path.write_text(orchestrator_context_source)
        orchestrator_context_rel = str(ctx_path.relative_to(module_root))

    ts = _now_iso()

    # 1+2. Append dispatch event FIRST (events.jsonl authoritative)
    event: dict = {
        "type": "dispatch",
        "stage": stage,
        "mode": mode,
        "run": new_run,
        "workdir": workdir_rel,
    }
    append_event(module, event, ts=ts)

    # 3. State mutation last (single write_task)
    st["status"] = "in_progress"
    st["freshness"] = "clean"
    st["current_run"] = new_run
    st["in_flight"].append({"run": new_run})
    write_task(module, task)

    # Build response
    result: dict = {
        "ok": True,
        "stage": stage,
        "mode": mode,
        "run": new_run,
        "workdir": workdir_rel,
        "skill": SKILL_OF[stage],
        "upstream_results": [
            str(_result_path(module, p).relative_to(module_root))
            for p in PREREQ_OF[stage]
        ],
    }

    if trigger:
        result["rework_trigger"] = trigger

    if orchestrator_context_rel is not None:
        result["orchestrator_context_path"] = orchestrator_context_rel

    return result


def _find_rework_trigger(module: str, target_stage: str) -> str | None:
    """Find the most recent rework_decision targeting this stage; return the
    canonical result.json path of the failed stage.

    Returns a path relative to asic/<module>/ pointing at the failed stage's
    canonical result.json:
        <area>/<failed_stage>/result.json

    Since 2026-05-06, canonical is hardlinked to the latest run's
    result.json regardless of pass/fail outcome, so this path always points
    at real fail data when target_stage's failed_stage just failed.
    """
    module_root = Path("asic") / module
    events = read_events(module)
    for event in reversed(events):
        if (
            event.get("type") == "rework_decision"
            and event.get("target_stage") == target_stage
        ):
            failed = event["failed_stage"]
            return str(_result_path(module, failed).relative_to(module_root))
        # Stop if we find a prior dispatch for this stage (scope to current cycle)
        if event.get("type") == "dispatch" and event.get("stage") == target_stage:
            break
    return None


# ── result.json validation ─────────────────────────────────────


def _plugin_root() -> Path:
    """Return the VeriPower plugin root (this script lives at <root>/framework/scripts/state.py)."""
    return Path(__file__).resolve().parents[2]


_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"


def _event_schema_path(event_type: str) -> Path:
    return (
        _plugin_root()
        / "framework"
        / "references"
        / "schemas"
        / "events"
        / f"{event_type}.schema.json"
    )


def _load_event_schema(event_type: str) -> dict | None:
    """Load event schema by type. Return None if no schema for this type."""
    p = _event_schema_path(event_type)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _validate_event(event: dict) -> tuple[bool, str]:
    """Validate event body against per-type schema. Returns (ok, error_msg)."""
    etype = event.get("type")
    if not etype:
        return False, "event missing 'type' field"
    schema = _load_event_schema(etype)
    if schema is None:
        return False, f"no schema for event type: {etype!r}"
    try:
        validator = Draft202012Validator(schema)
        errors = sorted(
            validator.iter_errors(event), key=lambda e: list(e.absolute_path)
        )
    except Exception as e:
        return False, f"event schema validation internal error: {type(e).__name__}: {e}"
    if errors:
        return False, _format_validation_errors(errors)
    return True, ""


def _load_envelope_resource() -> Resource:
    """Load envelope.schema.json as a referencing Resource for Registry-based $ref resolution."""
    p = _plugin_root() / "framework" / "references" / "schemas" / "envelope.schema.json"
    return Resource.from_contents(
        json.loads(p.read_text()), default_specification=DRAFT202012
    )


def _stage_schema_path(stage: str) -> Path:
    """Map stage name → its result.schema.json path under the owning skill."""
    skill_full = SKILL_OF[stage]  # e.g. "veripower:specification"
    skill_dir = skill_full.split(":", 1)[1]  # e.g. "specification"
    return _plugin_root() / "skills" / skill_dir / "references" / "result.schema.json"


def _format_validation_errors(errors: list[jsonschema.ValidationError]) -> str:
    """Format up to 3 validation errors with '+N more' suffix.

    Each error renders as: 'schema violation at $.path.to.field:
    error message (validator=...)'
    """
    if not errors:
        return ""
    head = errors[:3]
    tail_count = len(errors) - len(head)
    lines = []
    for e in head:
        path = "$" + "".join(
            f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in e.absolute_path
        )
        lines.append(
            f"schema violation at {path}: {e.message} (validator={e.validator})"
        )
    if tail_count > 0:
        lines.append(f"+{tail_count} more")
    return "; ".join(lines)


def validate_result(
    module: str, stage: str, run: int | None = None
) -> tuple[bool, str]:
    """Validate result.json against per-stage schema (envelope via $ref) + runtime checks.

    The static schema covers stage, status, artifacts, stage_specific shape.
    One check the schema can't express stays here as a runtime check:
      - module identity (must equal the --module arg).

    If `run` is provided, validates the run-specific result.json at runs/<run>/result.json
    instead of the canonical path.
    """
    if run is not None:
        p = _result_path(module, stage).parent / "runs" / str(run) / "result.json"
    else:
        p = _result_path(module, stage)
    if not p.exists():
        return False, f"result.json not found: {p}"
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return False, f"result.json parse error: {e}"

    schema_path = _stage_schema_path(stage)
    if not schema_path.exists():
        return False, f"per-stage schema not found: {schema_path}"

    try:
        stage_schema = json.loads(schema_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return False, f"per-stage schema parse error ({schema_path}): {e}"

    # Wrap envelope-loading + validator construction + iter_errors so the
    # (bool, str) return contract holds even under infrastructure failure
    # (corrupt envelope.schema.json, $ref URI mismatch, malformed schema).
    try:
        registry = Registry().with_resource(_ENVELOPE_URI, _load_envelope_resource())
        validator = Draft202012Validator(stage_schema, registry=registry)
        errors = sorted(
            validator.iter_errors(data), key=lambda e: list(e.absolute_path)
        )
    except Exception as e:
        return False, f"schema validation internal error: {type(e).__name__}: {e}"
    if errors:
        return False, _format_validation_errors(errors)

    if data.get("module") != module:
        return False, f"module mismatch: expected {module}, got {data.get('module')}"

    return True, ""


def cmd_complete(
    module: str,
    stage: str,
    *,
    run: int,
    outcome: str | None = None,
    reason: str | None = None,
    subagent_output_file: str | None = None,
) -> dict:
    """Complete a stage's run.

    Three-stage write order: compute → events first → state after.

    Branch logic:
    1. N not in in_flight → discarded (stale_dispatch); no state change
    2. N != current_run → discarded (superseded_run); remove from in_flight
    3. N == current_run → main path:
       - blocked → non-success finalize (canonical-derived terminal state)
       - schema-invalid → non-success finalize
       - prereq stale during exec → non-success finalize (reason: prereq_changed)
       - pass → promote → state pass/clean + cascade
       - fail → state fail/clean
       - promote failed → outcome.promote_failed; state stays in_progress/clean,
         run stays in in_flight (Orchestrator retries)
    """
    repair_partial_promote_if_needed(module, stage)
    # Best-effort: mirror async subagent transcript before any branch decision,
    # so the trace is preserved even for stale_dispatch / superseded_run /
    # promote_failed paths (all of which are useful for postmortem). workdir
    # path mirrors the canonical run dir for this stage/run.
    workdir = _result_path(module, stage).parent / "runs" / str(run)
    _mirror_subagent_trace(workdir, stage, subagent_output_file)
    task = read_task(module)
    st = task["stages"][stage]
    ts = _now_iso()

    in_flight_runs = {x["run"] for x in st["in_flight"]}

    # Branch 1: ghost / stale_dispatch (run not active at all)
    if run not in in_flight_runs:
        append_event(
            module,
            {
                "type": "outcome",
                "stage": stage,
                "run": run,
                "result_status": "discarded",
                "reason": "stale_dispatch",
            },
            ts=ts,
        )
        return {
            "action": "discarded",
            "result_status": "discarded",
            "reason_code": "stale_dispatch",
            "run": run,
        }

    # Branch 2: superseded_run (run was dispatched but a newer one took over)
    if run != st["current_run"]:
        # Compute: remove from in_flight
        st["in_flight"] = [x for x in st["in_flight"] if x["run"] != run]
        # Event first.
        append_event(
            module,
            {
                "type": "outcome",
                "stage": stage,
                "run": run,
                "result_status": "discarded",
                "reason": "superseded_run",
            },
            ts=ts,
        )
        # State after.
        write_task(module, task)
        return {
            "action": "discarded",
            "result_status": "discarded",
            "reason_code": "superseded_run",
            "run": run,
        }

    # Branch 3: N == current_run (active main path)

    def _non_success_finalize(reason_text: str, result_status: str) -> dict:
        """Unified rule for blocked/invalid/discarded(prereq_changed).
        Final status derived from canonical.status field."""
        # 1. Compute final state in-memory
        canonical_rj = _result_path(module, stage)
        st["in_flight"] = [x for x in st["in_flight"] if x["run"] != run]
        if canonical_rj.exists():
            st["status"] = json.loads(canonical_rj.read_text())["status"]
            st["freshness"] = "stale"  # canonical is from a prior run, not this one
        else:
            st["status"] = "not_started"
            st["freshness"] = "clean"
        # 2. Event first.
        append_event(
            module,
            {
                "type": "outcome",
                "stage": stage,
                "run": run,
                "result_status": result_status,
                "reason": reason_text,
            },
            ts=ts,
        )
        # 3. State after.
        write_task(module, task)
        return {"action": result_status, "result_status": result_status, "run": run}

    # Reap derive-mode: when --outcome is omitted, resolve the 3-way
    # (pass/fail/blocked) from THIS run's result.json here, so the Orchestrator
    # never reads the 5-7KB result.json just to extract .status. Missing /
    # unparseable / malformed-status → blocked (resolved before validate_result,
    # so a present-but-schema-invalid file still becomes 'invalid', not 'blocked').
    if outcome is None:
        if reason is not None:
            return {
                "ok": False,
                "error": "--reason is not accepted without --outcome "
                "(derive mode supplies the blocked reason itself)",
            }
        run_rj = _result_path(module, stage).parent / "runs" / str(run) / "result.json"
        if not run_rj.exists():
            outcome, reason = (
                "blocked",
                "result.json missing (stage crashed or exited without writing one)",
            )
        else:
            try:
                _derived = json.loads(run_rj.read_text())
            except (json.JSONDecodeError, OSError) as _e:
                outcome, reason = "blocked", f"result.json unparseable: {_e}"
            else:
                if not isinstance(_derived, dict):
                    outcome, reason = (
                        "blocked",
                        f"result.json is not a JSON object: {type(_derived).__name__}",
                    )
                else:
                    _status = _derived.get("status")
                    if _status in ("pass", "fail"):
                        outcome = _status
                    else:
                        outcome, reason = (
                            "blocked",
                            f"result.json status field malformed: {_status!r}",
                        )

    # Sub-branch: blocked
    if outcome == "blocked":
        err = _validate_reason(reason)
        if err:
            return {"ok": False, "error": f"--reason: {err}"}
        result = _non_success_finalize(reason, "blocked")
        result["reason"] = reason
        return result

    # outcome ∈ {pass, fail}; reason should not be present
    if outcome in ("pass", "fail") and reason is not None and reason.strip():
        return {
            "ok": False,
            "error": f"--reason is not accepted with --outcome={outcome}",
        }

    # Validate result.json schema (run-specific path)
    valid, err = validate_result(module, stage, run=run)
    if not valid:
        result = _non_success_finalize(err, "invalid")
        result["reason"] = err
        return result

    # Check prereq freshness still pass/clean
    for prereq in PREREQ_OF[stage]:
        pst = task["stages"][prereq]
        if pst["status"] != "pass" or pst["freshness"] != "clean":
            reason_text = (
                f"prerequisite {prereq} changed to "
                f"{pst['status']}/{pst['freshness']} during execution"
            )
            result = _non_success_finalize(reason_text, "discarded")
            result["reason_code"] = "prereq_changed"
            result["reason"] = reason_text
            return result

    # Check stage's own freshness: covers cascade-stale U-trajectory where
    # prereq churned (clean→stale→clean) entirely during in-flight execution
    # and is back to clean by reap time. The prereq check above misses this;
    # the stage's own stale flag is the only surviving evidence.
    if st["freshness"] == "stale":
        reason_text = (
            "stage was cascade-staled during execution; "
            "in-flight run measured against obsolete prereq snapshot"
        )
        result = _non_success_finalize(reason_text, "discarded")
        result["reason_code"] = "stage_staled_during_run"
        result["reason"] = reason_text
        return result

    # outcome == "fail"
    if outcome == "fail":
        # Promote runs/<run>/ → canonical first (canonical = latest run, pass or fail)
        try:
            promote(module, stage, run)
        except Exception as e:
            append_event(
                module,
                {
                    "type": "outcome",
                    "stage": stage,
                    "run": run,
                    "result_status": "promote_failed",
                    "reason": f"{type(e).__name__}: {e}",
                },
                ts=ts,
            )
            return {
                "action": "promote_failed",
                "result_status": "promote_failed",
                "reason": f"{type(e).__name__}: {e}",
                "run": run,
            }

        # Compute task state after successful promote (mirror pass branch)
        st["status"] = "fail"
        st["freshness"] = "clean"
        st["in_flight"] = [x for x in st["in_flight"] if x["run"] != run]

        # Event first.
        append_event(
            module,
            {
                "type": "outcome",
                "stage": stage,
                "run": run,
                "result_status": "fail",
            },
            ts=ts,
        )
        # State after.
        write_task(module, task)
        return {
            "action": "completed",
            "result_status": "fail",
            "run": run,
            "staled": [],
        }

    # outcome == "pass": promote then cascade
    try:
        promote(module, stage, run)
    except Exception as e:
        # promote_failed: state stays in_progress/clean, run remains in_flight.
        # Orchestrator can retry by calling cmd_complete again
        # No write_task; only event
        append_event(
            module,
            {
                "type": "outcome",
                "stage": stage,
                "run": run,
                "result_status": "promote_failed",
                "reason": f"{type(e).__name__}: {e}",
            },
            ts=ts,
        )
        return {
            "action": "promote_failed",
            "result_status": "promote_failed",
            "reason": f"{type(e).__name__}: {e}",
            "run": run,
        }

    # Compute final task state (including cascade).
    st["status"] = "pass"
    st["freshness"] = "clean"
    st["in_flight"] = [x for x in st["in_flight"] if x["run"] != run]
    staled = _compute_cascade(task, stage)

    # Events first.
    append_event(
        module,
        {
            "type": "outcome",
            "stage": stage,
            "run": run,
            "result_status": "pass",
        },
        ts=ts,
    )
    if staled:
        append_event(
            module,
            {
                "type": "cascade",
                "source_stage": stage,
                "staled": staled,
            },
            ts=ts,
        )

    # State after.
    write_task(module, task)

    return {
        "action": "completed",
        "result_status": "pass",
        "run": run,
        "staled": staled,
    }


def cmd_rework(module: str, failed_stage: str, target_stage: str, reason: str) -> dict:
    err = _validate_reason(reason)
    if err:
        return {"ok": False, "error": f"--reason: {err}"}

    task = read_task(module)
    tst = task["stages"][target_stage]

    # relaxed target constraint — allow pass / fail / in_progress
    if tst["status"] not in ("pass", "fail", "in_progress"):
        return {
            "ok": False,
            "error": f"target_stage {target_stage} is "
            f"{tst['status']}/{tst['freshness']} — must be "
            f"pass, fail, or in_progress",
        }

    if not is_dag_ancestor(target_stage, failed_stage):
        return {
            "ok": False,
            "error": f"target_stage {target_stage} is not a DAG "
            f"ancestor of failed_stage {failed_stage}",
        }

    # failed_stage must have been dispatched at least once — otherwise there's no
    # failed run to point at. In practice Orchestrator only enters cmd_rework after
    # observing fail/clean (which implies current_run is set), but we validate
    # explicitly so the rework_decision event always carries a valid run number.
    failed_run = task["stages"][failed_stage].get("current_run")
    if failed_run is None:
        return {
            "ok": False,
            "error": f"failed_stage {failed_stage} has no current_run "
            f"(never dispatched); cannot record rework_decision",
        }

    ts = _now_iso()

    # === 1. Compute (in-memory) ===
    tst["freshness"] = "stale"
    staled = _compute_cascade(task, target_stage)

    # === 2. Events first (rework_decision + optional cascade) ===
    append_event(
        module,
        {
            "type": "rework_decision",
            "failed_stage": failed_stage,
            "target_stage": target_stage,
            "reason": reason,
            "run": failed_run,
        },
        ts=ts,
    )
    if staled:
        append_event(
            module,
            {
                "type": "cascade",
                "source_stage": target_stage,
                "staled": staled,
            },
            ts=ts,
        )

    # === 3. State after (single write_task) ===
    write_task(module, task)

    return {
        "ok": True,
        "target_stage": target_stage,
        "staled": staled,
        "hint": (
            f"target stage {target_stage} marked stale (status preserved). "
            f"Orchestrator should re-dispatch this stage in the next eligibility scan."
        ),
    }


def cmd_invalidate_stage(module: str, stage: str, reason: str) -> dict:
    """Mark a stage AND its DAG-downstream stages stale, recording an `invalidate`
    event. Unlike cmd_rework: no failed_stage / DAG-ancestor argument, and it stales
    the SOURCE stage itself (cmd_rework stales only the target's downstream — see
    _compute_cascade). Use case: brainstorm-level rework recovery — the user re-ran the
    pre-pipeline brainstorm skill (new brainstorm.md) and needs specification re-derived
    from scratch with the downstream cascade. The fresh run gets an empty workdir
    (cmd_start mkdir's but does not seed), so specification routes to its first-run
    branch and re-derives in full from the current module-root brainstorm.md — no
    version/hash compare needed.

    Event type is `invalidate` (NOT rework_decision) so cmd_convergence's rework tally
    is not polluted (convergence counts rework_decision + failed_stage).
    """
    err = _validate_reason(reason)
    if err:
        return {"ok": False, "error": f"--reason: {err}"}

    task = read_task(module)
    st = task["stages"][stage]
    if st["status"] not in ("pass", "fail", "in_progress"):
        return {
            "ok": False,
            "error": f"stage {stage} is {st['status']}/{st['freshness']} — only a "
            f"stage that has run (pass/fail/in_progress) can be invalidated",
        }

    ts = _now_iso()

    # 1. Compute: stale the source itself + cascade downstream.
    st["freshness"] = "stale"
    staled = _compute_cascade(task, stage)

    # 2. Events first (invalidate + optional cascade).
    append_event(
        module,
        {
            "type": "invalidate",
            "stage": stage,
            "reason": reason,
        },
        ts=ts,
    )
    if staled:
        append_event(
            module,
            {
                "type": "cascade",
                "source_stage": stage,
                "staled": staled,
            },
            ts=ts,
        )

    # 3. State after (single write_task).
    write_task(module, task)

    return {
        "ok": True,
        "stage": stage,
        "staled": staled,
        "hint": (
            f"stage {stage} + downstream marked stale (status preserved). "
            f"Orchestrator re-dispatches {stage} on the next eligibility scan; "
            f"the new run's empty workdir routes it to first-run re-derivation."
        ),
    }


def convergence(events: list[dict], stage: str) -> dict:
    """Pure: rework-loop depth for a failing stage. Two-valued guideline."""
    cutoff_idx = 0
    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        if (
            e.get("type") == "outcome"
            and e.get("stage") == stage
            and e.get("result_status") == "pass"
        ):
            cutoff_idx = i + 1
            break
    by_target: dict[str, int] = {}
    total = 0
    for e in events[cutoff_idx:]:
        if e.get("type") == "rework_decision" and e.get("failed_stage") == stage:
            t = e["target_stage"]
            by_target[t] = by_target.get(t, 0) + 1
            total += 1
    guideline = "must_escalate" if total >= 3 else "continue"
    return {
        "stage": stage,
        "total_reworks": total,
        "by_target": by_target,
        "guideline": guideline,
    }


def cmd_convergence(module: str, stage: str) -> dict:
    return convergence(read_events(module), stage)


# Orchestrator may write only these via cmd_log; state.py auto-emits the rest
# (dispatch / outcome / cascade / rework_decision / invalidate).
_LOG_ALLOWED_TYPES = {
    "debug_dispatch",
    "debug_result",
    "escalation",
}


def cmd_log(module: str, event: dict) -> dict:
    etype = event.get("type", "")
    if etype not in _LOG_ALLOWED_TYPES:
        return {
            "ok": False,
            "error": f"unknown or auto-generated event type: {etype!r}. "
            f"Allowed via cmd_log: {sorted(_LOG_ALLOWED_TYPES)}",
        }
    try:
        append_event(module, event)
    except SystemExit as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


# ── CLI entry point ────────────────────────────────────────────


def _output(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="state.py", description="VeriPower state tool"
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser(
        "init",
        help="Initialize task.json for a module (idempotent). Returns {ok, created}.",
    )
    p_init.add_argument("--module", required=True, help="Module name (e.g. my_module)")

    # status
    p_status = sub.add_parser(
        "status",
        help="Read current stage statuses. Returns {module, stages: {<stage>: {status, freshness, current_run, in_flight}}}.",
    )
    p_status.add_argument("--module", required=True, help="Module name")

    # start
    p_start = sub.add_parser(
        "start",
        help="Dispatch a stage run. Returns {ok, stage, mode (forward|rework), run, workdir, skill, upstream_results, [rework_trigger], [orchestrator_context_path]}.",
    )
    p_start.add_argument("--module", required=True, help="Module name")
    p_start.add_argument("--stage", required=True, choices=FORWARD_PRIORITY)
    p_start.add_argument(
        "--orchestrator-context",
        metavar="FILE_OR_-",
        default=None,
        help="Optional: read orchestrator_context content from FILE (or '-' for stdin); "
        "writes to <workdir>/orchestrator-context.md.",
    )

    # complete
    p_complete = sub.add_parser(
        "complete",
        help="Record outcome of a run. Returns {action, result_status, run, staled} on success or {action, reason|reason_code, run} for discarded/blocked/invalid/promote_failed.",
    )
    p_complete.add_argument("--module", required=True, help="Module name")
    p_complete.add_argument("--stage", required=True, choices=FORWARD_PRIORITY)
    p_complete.add_argument(
        "--run", required=True, type=int, help="Run number from `start` output"
    )
    p_complete.add_argument(
        "--outcome",
        required=False,
        default=None,
        choices=["pass", "fail", "blocked"],
        help="Optional. Omit at reap: cmd_complete reads the run's result.json and derives "
        "pass/fail, or blocked (missing/unparseable/malformed status). When given, forces "
        "that outcome; invalid/discarded/promote_failed are internally derived either way",
    )
    p_complete.add_argument(
        "--reason",
        default=None,
        help="Required when --outcome=blocked; forbidden for pass/fail",
    )
    p_complete.add_argument(
        "--subagent-output-file",
        default=None,
        help="Optional /tmp/.../tasks/<agent_id>.output path "
        "from the async Task launch tool_result (or the "
        "task-notification <output-file> tag value). When "
        "provided, transcript is best-effort mirrored to "
        "<workdir>/.subagent_traces/<stage>-<agent_id>.output "
        "so it outlives Claude Code /tmp cleanup. Optional "
        "for sync dispatch (specification / simulation-plan).",
    )

    # rework
    p_rework = sub.add_parser(
        "rework",
        help="Mark target_stage stale and record rework_decision event. Returns {ok, target_stage, staled, hint}.",
    )
    p_rework.add_argument("--module", required=True, help="Module name")
    p_rework.add_argument(
        "--failed-stage",
        required=True,
        choices=FORWARD_PRIORITY,
        help="Stage that just failed, triggering the rework",
    )
    p_rework.add_argument(
        "--target-stage",
        required=True,
        choices=FORWARD_PRIORITY,
        help="DAG ancestor to re-run (must be pass/fail/in_progress)",
    )
    p_rework.add_argument(
        "--reason", required=True, help="Human-readable justification (non-empty)"
    )

    # invalidate-stage
    p_inval = sub.add_parser(
        "invalidate-stage",
        help="Mark a stage + its DAG-downstream stale (records an `invalidate` "
        "event; does NOT count toward convergence). Returns {ok, stage, staled, hint}.",
    )
    p_inval.add_argument("--module", required=True, help="Module name")
    p_inval.add_argument(
        "--stage",
        required=True,
        choices=FORWARD_PRIORITY,
        help="Stage to invalidate (typically specification, for brainstorm-level rework)",
    )
    p_inval.add_argument(
        "--reason", required=True, help="Human-readable justification (non-empty)"
    )

    # convergence
    p_conv = sub.add_parser(
        "convergence",
        help="Check rework loop depth for a failing stage. Returns {stage, total_reworks, by_target, guideline (continue|must_escalate)}.",
    )
    p_conv.add_argument("--module", required=True, help="Module name")
    p_conv.add_argument(
        "--stage",
        required=True,
        choices=FORWARD_PRIORITY,
        help="The failing stage to measure rework depth for",
    )

    # log
    p_log = sub.add_parser(
        "log",
        help="Append an Orchestrator-authored event to events.jsonl. Returns {ok}.",
    )
    p_log.add_argument("--module", required=True, help="Module name")
    p_log.add_argument(
        "--event",
        required=True,
        help="JSON object with 'type' field; allowed types: debug_dispatch | debug_result | escalation",
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # `start` pre-reads --orchestrator-context FILE outside the SystemExit
    # catcher below so that file-read errors emit a clean structured envelope
    # and exit 1, rather than getting wrapped in a second `{"ok": false, "error": "1"}` envelope.
    ctx_source = None
    if args.command == "start" and args.orchestrator_context:
        if args.orchestrator_context == "-":
            ctx_source = sys.stdin.read()
        else:
            try:
                ctx_source = Path(args.orchestrator_context).read_text()
            except OSError as e:
                _output(
                    {
                        "ok": False,
                        "error": f"--orchestrator-context: cannot read {args.orchestrator_context!r}: {e}",
                    }
                )
                sys.exit(1)

    try:
        if args.command == "init":
            _output(cmd_init(args.module))
        elif args.command == "status":
            _output(cmd_status(args.module))
        elif args.command == "start":
            _output(
                cmd_start(
                    args.module, args.stage, orchestrator_context_source=ctx_source
                )
            )
        elif args.command == "complete":
            _output(
                cmd_complete(
                    args.module,
                    args.stage,
                    run=args.run,
                    outcome=args.outcome,
                    reason=args.reason,
                    subagent_output_file=args.subagent_output_file,
                )
            )
        elif args.command == "rework":
            _output(
                cmd_rework(
                    args.module, args.failed_stage, args.target_stage, args.reason
                )
            )
        elif args.command == "invalidate-stage":
            _output(cmd_invalidate_stage(args.module, args.stage, args.reason))
        elif args.command == "convergence":
            _output(cmd_convergence(args.module, args.stage))
        elif args.command == "log":
            try:
                event = json.loads(args.event)
            except json.JSONDecodeError as e:
                _output({"ok": False, "error": f"--event JSON parse error: {e}"})
                return
            _output(cmd_log(args.module, event))
    except SystemExit as e:
        _output({"ok": False, "error": str(e)})


if __name__ == "__main__":
    main()
