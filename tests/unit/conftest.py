"""Shared helpers for tests under tests/unit/.

Two helpers replace patterns that were duplicated 3-5 times across the
unit test files. Callers import explicitly (`from conftest import X`)
rather than rely on pytest fixture injection — each helper takes plain
(module, stage[, run, ...]) args, not pytest context, so a fixture would
add a layer without value.

- `bootstrap_prereqs_pass_clean(module, stage)` — BFS over `state.PREREQ_OF`
  to mark all transitive prereqs of `stage` as pass/clean. Caller is
  expected to have `cmd_init`'d the module already.

- `write_run_result(module, stage, run, *, status, stage_specific, artifacts)`
  — write a schema-valid `result.json` to `runs/<run>/result.json`.
  `stage_specific` defaults to `STAGE_SPECIFIC_MINIMAL[stage]`; on
  `status=fail`, `fail_reason` and (for synthesis / timing-analysis /
  power-analysis) `failure_kind` are auto-filled.

Uses `from framework.scripts import state` (Python 3 namespace package;
`pytest.ini`'s `pythonpath = .` puts repo root on `sys.path`).
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

from _skills_sot import STAGE_SPECIFIC_MINIMAL


def bootstrap_prereqs_pass_clean(module: str, stage: str) -> None:
    from framework.scripts import state

    task = state.read_task(module)
    visited: set[str] = set()
    queue = deque(state.PREREQ_OF[stage])
    while queue:
        p = queue.popleft()
        if p in visited:
            continue
        visited.add(p)
        task["stages"][p] = {
            "status": "pass",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [],
        }
        queue.extend(state.PREREQ_OF[p])
    state.write_task(module, task)


def write_run_result(
    module: str,
    stage: str,
    run: int,
    *,
    status: str = "pass",
    stage_specific: dict[str, Any] | None = None,
    artifacts: list[dict[str, str]] | None = None,
) -> None:
    from framework.scripts import state

    rj = state._result_path(module, stage).parent / "runs" / str(run) / "result.json"
    rj.parent.mkdir(parents=True, exist_ok=True)

    if stage_specific is None:
        stage_specific = STAGE_SPECIFIC_MINIMAL[stage]
    if status == "fail":
        if "fail_reason" not in stage_specific:
            stage_specific = {**stage_specific, "fail_reason": "test fail"}
        if (
            stage in ("synthesis", "timing-analysis", "power-analysis")
            and "failure_kind" not in stage_specific
        ):
            stage_specific = {**stage_specific, "failure_kind": "infra"}

    rj.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": stage,
                "module": module,
                "produced_at": "2026-05-11T00:00:00Z",
                "status": status,
                "artifacts": artifacts or [],
                "stage_specific": stage_specific,
            }
        )
    )
