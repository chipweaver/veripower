"""VeriPower pipeline topology — the structural SSoT (the stage DAG).

Dependency-light leaf: NO jsonschema/referencing imports, so importers
(state.py and the orchestrate.py decider) do not inherit them.
Holds the DAG constants, graph queries, and the eligibility predicate.
No I/O, no state. Import it the bare way (`import topology`), never via
`framework.scripts.topology` (that would split it into a 2nd module object).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

FORWARD_PRIORITY = [
    "specification",
    "simulation-plan",
    "rtl-design",
    "lint-cdc",
    "synthesis",
    "timing-analysis",
    "simulation",
    "power-analysis",
    "frontend-signoff",
]

PREREQ_OF: dict[str, list[str]] = {
    "specification": [],
    "simulation-plan": ["specification"],
    "rtl-design": ["simulation-plan"],
    "lint-cdc": ["rtl-design"],
    "synthesis": ["lint-cdc"],
    "timing-analysis": ["synthesis"],
    "simulation": ["rtl-design"],
    "power-analysis": ["simulation", "timing-analysis"],
    "frontend-signoff": ["power-analysis"],
}

SKILL_OF: dict[str, str] = {
    "specification": "veripower:specification",
    "rtl-design": "veripower:rtl-design",
    "lint-cdc": "veripower:lint-cdc",
    "simulation-plan": "veripower:simulation-plan",
    "simulation": "veripower:simulation",
    "synthesis": "veripower:synthesis",
    "power-analysis": "veripower:power-analysis",
    "timing-analysis": "veripower:timing-analysis",
    "frontend-signoff": "veripower:frontend-signoff",
}

_RESULT_DIR: dict[str, tuple[str, ...]] = {
    "specification": ("Design", "specification"),
    "rtl-design": ("Design", "rtl-design"),
    "lint-cdc": ("Design", "lint-cdc"),
    "simulation-plan": ("Verification", "simulation-plan"),
    "simulation": ("Verification", "simulation"),
    "synthesis": ("Design", "synthesis"),
    "power-analysis": ("Verification", "power-analysis"),
    "timing-analysis": ("Design", "timing-analysis"),
    "frontend-signoff": ("frontend-signoff",),
}

_CHILDREN_OF: dict[str, list[str]] = {s: [] for s in FORWARD_PRIORITY}
for _s, _prereqs in PREREQ_OF.items():
    for _p in _prereqs:
        _CHILDREN_OF[_p].append(_s)


def _result_path(module: str, stage: str) -> Path:
    return Path("asic", module, *_RESULT_DIR[stage], "result.json")


def is_dag_ancestor(candidate: str, of: str) -> bool:
    """True if candidate is a transitive prerequisite of 'of'."""
    visited: set[str] = set()
    queue = deque(PREREQ_OF.get(of, []))
    while queue:
        s = queue.popleft()
        if s == candidate:
            return True
        if s not in visited:
            visited.add(s)
            queue.extend(PREREQ_OF.get(s, []))
    return False


def descendants(stage: str) -> list[str]:
    """Transitive children in deterministic BFS order (stable `staled` lists)."""
    out: list[str] = []
    seen: set[str] = set()
    queue = deque(_CHILDREN_OF.get(stage, []))
    while queue:
        s = queue.popleft()
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        queue.extend(_CHILDREN_OF.get(s, []))
    return out


def eligible(stage: str, task: dict) -> bool:
    """Dispatch eligibility — mirrors cmd_start's gate (state.py) exactly:
    own status is not_started/clean (forward) or */stale (rework, incl
    in_progress/stale); all prerequisites are pass/clean."""
    st = task["stages"][stage]
    status, fresh = st["status"], st["freshness"]
    if fresh == "stale":
        ok_self = True
    elif status == "not_started" and fresh == "clean":
        ok_self = True
    else:  # in_progress/clean, pass/clean, fail/clean
        ok_self = False
    if not ok_self:
        return False
    return all(
        task["stages"][p]["status"] == "pass"
        and task["stages"][p]["freshness"] == "clean"
        for p in PREREQ_OF[stage]
    )
