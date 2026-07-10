"""No SKILL.md instructs its executing agent to gate on an upstream stage's
`result.json` `status` field before proceeding (spec §4.3: "gate 读删除" — the
kernel's dispatchability check already guarantees prerequisites at dispatch
time, so no stage executor may re-check them as a precondition).

Grep-style regression guard, mirroring test_no_skill_decided_blocked.py's
static-text idiom: locks the exact phrasing the C6 sweep removed (the `status
≠ pass` / `MUST be status=pass` / `fail fast when missing or not pass` gate
patterns previously found in lint-cdc, synthesis, timing-analysis, simulation,
simulation-plan, and power-analysis SKILL.md). A skill re-introducing the gate
under new phrasing would not be caught by this static grep — this locks the
specific regression class, not the general principle.

frontend-signoff is deliberately NOT a false positive here: its `signoff
finalize` verb aggregates every upstream envelope into the sign-off verdict —
that IS the stage's deliverable, not a redundant pre-check duplicating the
kernel's dispatchability guarantee — and it carries none of the patterns below.
"""

import re

from _skills_sot import PLUGIN_ROOT, SKILL_DIRS

_GATE_PATTERNS = [
    re.compile(r"status≠pass"),
    re.compile(r"MUST be `status=pass`"),
    re.compile(r"fail fast when missing or not `pass`"),
]


def test_no_skill_gates_on_upstream_status():
    offenders = []
    for name in SKILL_DIRS:
        text = (PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        for pat in _GATE_PATTERNS:
            if pat.search(text):
                offenders.append(f"{name}/SKILL.md: {pat.pattern!r}")
    assert offenders == [], (
        "SKILL.md instructs an upstream result.json status=pass gate read; "
        "the kernel's dispatchability check already guarantees this (spec "
        f"§4.3 — the deletion is total): {offenders}"
    )
