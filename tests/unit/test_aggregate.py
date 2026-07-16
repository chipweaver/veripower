"""Tests for eval/aggregate/aggregate.py — log -> cost metrics (C3)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval" / "aggregate"))
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import aggregate  # noqa: E402


def _events_module(repo_root, module, events):
    d = repo_root / "asic" / module
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _outcome(rule, run, cost=None, ts="2026-07-16T00:00:10Z"):
    e = {
        "ts": ts,
        "type": "outcome",
        "rule": rule,
        "run": run,
        "verdict": "pass",
        "outputs": {},
        "proofs": [],
        "tool_versions": {},
    }
    if cost is not None:
        e["cost_tokens"] = cost
    return e


def _dispatch(rule, run, ts="2026-07-16T00:00:00Z"):
    return {"ts": ts, "type": "dispatch", "rule": rule, "run": run, "params": {}}


def test_aggregate_run_sums_task_and_mainthread(tmp_path):
    repo = tmp_path
    # synthesis carries cost_tokens on its outcome (new-run path); dispatch 10s earlier
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1, ts="2026-07-16T00:00:00Z"),
            _outcome(
                "synthesis",
                1,
                cost={
                    "total_tokens": 500,
                    "input_tokens": 100,
                    "output_tokens": 400,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "source": "subagent_trace",
                },
                ts="2026-07-16T00:00:10Z",
            ),
        ],
    )
    # a fake session transcript (main-thread + orchestrator cost)
    sess = repo / "sess.jsonl"
    sess.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "s1",
                    "role": "assistant",
                    "model": "claude-x",
                    "usage": {
                        "input_tokens": 70,
                        "output_tokens": 30,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }
        )
        + "\n"
    )

    run = {
        "arm": "full",
        "design": "d",
        "seed": 1,
        "module": "m",
        "session_transcripts": [str(sess)],
    }
    m = aggregate.aggregate_run(run, repo)
    assert m["task_tokens"] == 500
    assert m["mainthread_tokens"] == 100
    assert m["total_tokens"] == 600
    assert m["wallclock_sec"] == 10.0
    assert m["cost_partial"] is False


def test_task_cost_fallback_rescan_when_outcome_has_no_cost(tmp_path):
    """Old run: outcome lacks cost_tokens -> re-scan .subagent_traces/."""
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1),
            _outcome("synthesis", 1, cost=None),
        ],
    )
    # place a trace under the run's workdir (Design/synthesis/runs/1/.subagent_traces)
    tdir = (
        repo / "asic" / "m" / "Design" / "synthesis" / "runs" / "1" / ".subagent_traces"
    )
    tdir.mkdir(parents=True)
    (tdir / "synthesis-aX.output").write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "t1",
                    "role": "assistant",
                    "model": "claude-x",
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 22,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }
        )
        + "\n"
    )
    run = {
        "arm": "full",
        "design": "d",
        "seed": 1,
        "module": "m",
        "session_transcripts": [],
    }
    m = aggregate.aggregate_run(run, repo)
    assert m["task_tokens"] == 33  # re-scanned 11+22
    assert m["total_tokens"] == 33


def test_missing_session_transcript_marks_partial(tmp_path):
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1),
            _outcome(
                "synthesis",
                1,
                cost={
                    "total_tokens": 5,
                    "input_tokens": 5,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            ),
        ],
    )
    run = {
        "arm": "full",
        "design": "d",
        "seed": 1,
        "module": "m",
        "session_transcripts": [str(repo / "does_not_exist.jsonl")],
    }
    m = aggregate.aggregate_run(run, repo)
    assert m["cost_partial"] is True  # transcript missing


def test_task_tokens_excludes_mainthread_and_non_rules_outcomes(tmp_path):
    """Mixed log: a task-execution outcome (synthesis), a main-thread outcome
    (specification), and a non-RULES-registry outcome (frontend-signoff — retired
    to a kernel verb) all carry cost_tokens. task_tokens must count ONLY the
    task-execution one; the other two belong to the session transcript, not
    task_tokens. This locks the execution == "task" gate against silent breakage
    (the old assertions were identities that would pass even if the gate broke)."""
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1),
            _outcome(
                "synthesis",
                1,
                cost={
                    "total_tokens": 500,
                    "input_tokens": 100,
                    "output_tokens": 400,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            ),
            _dispatch("specification", 1),
            _outcome(
                "specification",
                1,
                cost={
                    "total_tokens": 9000,
                    "input_tokens": 9000,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            ),
            _dispatch("frontend-signoff", 1),
            _outcome(
                "frontend-signoff",
                1,
                cost={
                    "total_tokens": 7000,
                    "input_tokens": 7000,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            ),
        ],
    )
    run = {
        "arm": "full",
        "design": "d",
        "seed": 1,
        "module": "m",
        "session_transcripts": [],
    }
    m = aggregate.aggregate_run(run, repo)
    assert m["task_tokens"] == 500
    assert m["total_tokens"] == 500


def test_wallclock_does_not_multicount_on_re_reap(tmp_path):
    """A (rule, run) key with dispatch -> outcome, then a SECOND outcome with no
    new dispatch (the crash-mid-promote repair path and the pin/regrade path —
    kernel.py cmd_reap explicitly allows re-reaping an already-outcome'd run)
    must not re-match the stale dispatch. wallclock_sec must equal only the
    first dispatch -> outcome delta; the re-reap outcome contributes nothing."""
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1, ts="2026-07-16T00:00:00Z"),
            _outcome("synthesis", 1, cost=None, ts="2026-07-16T00:00:10Z"),
            # re-reap / regrade: another outcome for the same key, no new dispatch
            _outcome("synthesis", 1, cost=None, ts="2026-07-17T00:00:00Z"),
        ],
    )
    run = {
        "arm": "full",
        "design": "d",
        "seed": 1,
        "module": "m",
        "session_transcripts": [],
    }
    m = aggregate.aggregate_run(run, repo)
    assert m["wallclock_sec"] == 10.0


def test_task_cost_does_not_multicount_on_re_reap(tmp_path):
    """Symmetric to test_wallclock_does_not_multicount_on_re_reap: a (rule, run)
    key with dispatch -> outcome (cost_tokens=500), then a SECOND outcome for the
    same key with no new dispatch (regrade — kernel.py cmd_reap explicitly allows
    re-reaping an already-outcome'd run), also carrying cost_tokens. task_tokens
    must count the run once (the latest outcome), not sum both outcomes."""
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1, ts="2026-07-16T00:00:00Z"),
            _outcome(
                "synthesis",
                1,
                cost={
                    "total_tokens": 500,
                    "input_tokens": 100,
                    "output_tokens": 400,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                ts="2026-07-16T00:00:10Z",
            ),
            # re-reap / regrade: another outcome for the same key, no new dispatch
            _outcome(
                "synthesis",
                1,
                cost={
                    "total_tokens": 500,
                    "input_tokens": 100,
                    "output_tokens": 400,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                ts="2026-07-17T00:00:00Z",
            ),
        ],
    )
    run = {
        "arm": "full",
        "design": "d",
        "seed": 1,
        "module": "m",
        "session_transcripts": [],
    }
    m = aggregate.aggregate_run(run, repo)
    assert m["task_tokens"] == 500


def test_real_fa_core_fsa_acceptance():
    """Acceptance: run against the real in-repo module (old run, no
    cost_tokens on outcomes -> pure re-scan). Proves the pipe works."""
    repo = ROOT
    if not (repo / "asic" / "fa_core_fsa" / "events.jsonl").exists():
        import pytest

        pytest.skip("fa_core_fsa module absent")
    run = {
        "arm": "full",
        "design": "fa",
        "seed": 1,
        "module": "fa_core_fsa",
        "session_transcripts": [],
    }
    m = aggregate.aggregate_run(run, repo)
    assert m["task_tokens"] > 0  # re-scanned from real .subagent_traces
    assert m["total_tokens"] == m["task_tokens"] + m["mainthread_tokens"]
