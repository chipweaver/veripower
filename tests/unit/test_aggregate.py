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


def _write_subagent_trace(repo, module, rule, run, session_id, trace_name="a1"):
    """Place a mirrored .subagent_traces/*.output whose first line carries
    sessionId = the parent orchestrator session (verified fact: every
    subagent trace line records the PARENT session's id, not its own)."""
    import rules

    tdir = (
        repo
        / "asic"
        / module
        / Path(*rules.workdir_root(rule))
        / "runs"
        / str(run)
        / ".subagent_traces"
    )
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{rule}-{trace_name}.output").write_text(
        json.dumps({"sessionId": session_id, "type": "user"}) + "\n"
    )


def _write_session_transcript(projects_dir, session_id, input_tokens, output_tokens):
    projects_dir.mkdir(parents=True, exist_ok=True)
    (projects_dir / f"{session_id}.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": f"msg-{session_id}",
                    "role": "assistant",
                    "model": "claude-x",
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }
        )
        + "\n"
    )


def test_auto_derive_single_session(tmp_path):
    """No manifest session_transcripts + one task-execution outcome whose
    trace carries sessionId=S1 -> mainthread auto-derived from S1.jsonl,
    session_ids == ["S1"], source == auto-from-traces, clean is True."""
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1),
            _outcome("synthesis", 1, cost=None),  # no cost_tokens -> re-scan too
        ],
    )
    _write_subagent_trace(repo, "m", "synthesis", 1, session_id="S1")
    projects_dir = tmp_path / "fake_projects"
    _write_session_transcript(projects_dir, "S1", input_tokens=70, output_tokens=30)

    run = {"arm": "full", "design": "d", "seed": 1, "module": "m"}
    m = aggregate.aggregate_run(run, repo, claude_projects_dir=projects_dir)
    assert m["mainthread_tokens"] == 100
    assert m["session_ids"] == ["S1"]
    assert m["mainthread_source"] == "auto-from-traces"
    assert m["mainthread_clean"] is True
    assert m["total_tokens"] == m["task_tokens"] + m["mainthread_tokens"]


def test_auto_derive_multi_session_not_clean(tmp_path):
    """Two task outcomes whose traces carry distinct sessionIds -> both are
    harvested, value is still summed, but mainthread_clean is False (the
    caveat: session granularity != module granularity, and any orchestrator
    session that dispatched no task stage stays invisible)."""
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1),
            _outcome("synthesis", 1, cost=None),
            _dispatch("lint-cdc", 1),
            _outcome("lint-cdc", 1, cost=None),
        ],
    )
    _write_subagent_trace(repo, "m", "synthesis", 1, session_id="S1")
    _write_subagent_trace(repo, "m", "lint-cdc", 1, session_id="S2")
    projects_dir = tmp_path / "fake_projects"
    _write_session_transcript(projects_dir, "S1", input_tokens=70, output_tokens=30)
    _write_session_transcript(projects_dir, "S2", input_tokens=5, output_tokens=5)

    run = {"arm": "full", "design": "d", "seed": 1, "module": "m"}
    m = aggregate.aggregate_run(run, repo, claude_projects_dir=projects_dir)
    assert m["session_ids"] == ["S1", "S2"]
    assert m["mainthread_source"] == "auto-from-traces"
    assert m["mainthread_clean"] is False
    assert m["mainthread_tokens"] == 110  # still best-effort summed


def test_manifest_session_transcripts_take_precedence(tmp_path):
    """A manifest-supplied session_transcripts list is used as-is (today's
    path); the auto-derive path must not run, and the operator-vouched
    transcript is treated as clean."""
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1),
            _outcome("synthesis", 1, cost=None),
        ],
    )
    # trace carries a DIFFERENT sessionId than the manifest transcript, to
    # prove the auto path is not consulted when the manifest wins.
    _write_subagent_trace(repo, "m", "synthesis", 1, session_id="S-ignored")
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
    projects_dir = tmp_path / "fake_projects"  # deliberately never populated

    run = {
        "arm": "full",
        "design": "d",
        "seed": 1,
        "module": "m",
        "session_transcripts": [str(sess)],
    }
    m = aggregate.aggregate_run(run, repo, claude_projects_dir=projects_dir)
    assert m["mainthread_source"] == "manifest"
    assert m["session_ids"] == []
    assert m["mainthread_clean"] is True
    assert m["mainthread_tokens"] == 100


def test_auto_derive_missing_session_file_marks_partial(tmp_path):
    """A harvested sessionId whose <sid>.jsonl is absent from the fake
    projects dir must mark cost_partial without crashing (existing
    _mainthread_cost missing-file handling, reused as-is)."""
    repo = tmp_path
    _events_module(
        repo,
        "m",
        [
            _dispatch("synthesis", 1),
            _outcome("synthesis", 1, cost=None),
        ],
    )
    _write_subagent_trace(repo, "m", "synthesis", 1, session_id="S-missing")
    projects_dir = tmp_path / "fake_projects"
    projects_dir.mkdir(parents=True)  # exists, but S-missing.jsonl does not

    run = {"arm": "full", "design": "d", "seed": 1, "module": "m"}
    m = aggregate.aggregate_run(run, repo, claude_projects_dir=projects_dir)
    assert m["cost_partial"] is True
    assert m["session_ids"] == ["S-missing"]


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
