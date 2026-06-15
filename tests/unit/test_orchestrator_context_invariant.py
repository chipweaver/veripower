"""Freeze the orchestrator_context_path lifecycle (D4).

The `orchestrator_context` channel: Orchestrator passes content via
`cmd_start(..., orchestrator_context_source=…)`, state.py writes
`runs/<N>/orchestrator-context.md`, and the dispatch payload returns
`orchestrator_context_path` (module-root-relative). The dispatched
subagent reads that sibling file.

Invariants this module locks against regression — analogous to how
test_dispatcher_trigger_invariant locks the three rework-mode paths:

I1 — Round-trip: content in → file at returned path contains the content
I2 — Absent when no source provided
I3 — Returned path is module-root-relative (no leading `asic/`, no /)
I4 — Path includes the dispatched run number
I5 — Not promoted to canonical: the per-dispatch hint
     stays under `runs/<N>/`; `Design/<stage>/orchestrator-context.md` is
     never created by the promote step.
I6 — Compute-phase write (line 410-417 in state.py): if file write would
     fail, no event or state mutation has occurred yet. Verified by
     pre-checking that no `dispatch` event was appended on OSError.
"""

from pathlib import Path

import pytest
from conftest import write_run_result

from framework.scripts.state import (
    _result_path,
    cmd_complete,
    cmd_init,
    cmd_start,
    read_events,
)


def _module_root(module: str) -> Path:
    return Path("asic") / module


def test_i1_roundtrip_content_written(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cmd_init("M1")
    r = cmd_start(
        "M1", "specification", orchestrator_context_source="hint: focus on FSM coverage"
    )
    assert r["ok"] and "orchestrator_context_path" in r
    rel = r["orchestrator_context_path"]
    f = _module_root("M1") / rel
    assert f.is_file()
    assert f.read_text() == "hint: focus on FSM coverage"


def test_i2_absent_when_source_none(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cmd_init("M1")
    r = cmd_start("M1", "specification")
    assert r["ok"]
    assert "orchestrator_context_path" not in r
    workdir = _result_path("M1", "specification").parent / "runs" / str(r["run"])
    assert not (workdir / "orchestrator-context.md").exists()


def test_i3_path_is_module_root_relative(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cmd_init("M1")
    r = cmd_start("M1", "specification", orchestrator_context_source="x")
    rel = r["orchestrator_context_path"]
    assert not rel.startswith("/"), f"expected relative path, got absolute: {rel!r}"
    assert not rel.startswith("asic/"), (
        f"path is module-root-relative; asic/<module>/ prefix must be "
        f"stripped, got {rel!r}"
    )


def test_i4_path_includes_dispatched_run_number(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cmd_init("M1")
    r = cmd_start("M1", "specification", orchestrator_context_source="x")
    rel = r["orchestrator_context_path"]
    assert f"runs/{r['run']}/" in rel, (
        f"path should sit under runs/{r['run']}/, got {rel!r}"
    )


def test_i5_not_promoted_to_canonical(tmp_path, monkeypatch) -> None:
    """orchestrator-context.md is an ephemeral per-dispatch
    hint and must NOT be copied to the canonical Design/<stage>/ root by the
    promote step. The run-specific copy persists for forensic inspection.
    """
    monkeypatch.chdir(tmp_path)
    cmd_init("M1")
    r = cmd_start("M1", "specification", orchestrator_context_source="rework hint")
    run = r["run"]
    write_run_result("M1", "specification", run)
    res = cmd_complete("M1", "specification", run=run, outcome="pass")
    assert res["action"] == "completed" and res["result_status"] == "pass"

    canonical_dir = _result_path("M1", "specification").parent
    # The promote step does NOT lift orchestrator-context.md to the
    # canonical Design/specification/ root.
    assert not (canonical_dir / "orchestrator-context.md").exists(), (
        "orchestrator-context.md must not be promoted to canonical "
        "(ephemeral per-dispatch hint)"
    )
    # The run-specific copy is retained.
    assert (canonical_dir / "runs" / str(run) / "orchestrator-context.md").is_file()


def test_i6_no_state_mutation_on_write_failure(tmp_path, monkeypatch) -> None:
    """If the orchestrator-context.md write raises, cmd_start must propagate
    without appending a dispatch event or flipping the stage to in_progress.

    Achieved by the compute-phase ordering: the file write happens
    before the event append and state mutation (state.py:413-417).
    """
    monkeypatch.chdir(tmp_path)
    cmd_init("M1")

    real_write_text = Path.write_text

    def fake_write_text(self, data, *args, **kwargs):
        if self.name == "orchestrator-context.md":
            raise OSError("simulated write failure")
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)

    with pytest.raises(OSError):
        cmd_start(
            "M1", "specification", orchestrator_context_source="should not survive"
        )

    # No dispatch event should have been appended.
    events = read_events("M1")
    dispatch_events = [e for e in events if e["type"] == "dispatch"]
    assert dispatch_events == [], (
        f"orchestrator-context write failure must short-circuit before "
        f"event append; found {len(dispatch_events)} dispatch event(s)"
    )
