"""SKILL.md context-variable assertions.

Rules:
  - The `{var}` placeholders appearing in SKILL.md ⊆ canonical 4:
    `{workdir}` / `{module}` / `{failing_result}` / `{directive_path}`.
  - SKILL.md must not hardcode `asic/<M>` / `asic/<module>` / `runs/<N>`
    paths; always use `{workdir}` and the other context variables.
  - Variables injected by the dispatcher template
    (`stage-subagent.md.tpl`) must be a superset of the canonical 4;
    template-only extras (`{mode}` / `{stage}` / `{run}` / `{skill}`) must
    not appear in any SKILL.md.
"""

import re
from pathlib import Path

import pytest
from _skills_sot import PLUGIN_ROOT, SKILL_DIRS

CANONICAL_VARS: set[str] = {
    "workdir",
    "module",
    "failing_result",
    "directive_path",
}

# Hardcoded path patterns (must not appear in SKILL.md).
HARDCODE_PATTERNS = [
    re.compile(r"asic/<[A-Za-z]"),  # asic/<M / asic/<module>
    re.compile(r"runs/<[0-9N]"),  # runs/<N> / runs/<0>
]

PLACEHOLDER_PATTERN = re.compile(r"\{([a-z_]+)\}")


def _audit_skill(skill_md: Path) -> list[str]:
    """Return the list of violations; empty list = compliant."""
    text = skill_md.read_text(encoding="utf-8")
    violations = []
    # 1. Placeholder audit.
    placeholders = set(PLACEHOLDER_PATTERN.findall(text))
    illegal = placeholders - CANONICAL_VARS
    if illegal:
        violations.append(f"non-canonical placeholders: {sorted(illegal)}")
    # 2. Hardcoded path audit.
    for pat in HARDCODE_PATTERNS:
        matches = pat.findall(text)
        if matches:
            violations.append(
                f"hardcoded path pattern '{pat.pattern}' present (count={len(matches)})"
            )
    return violations


@pytest.mark.parametrize("skill_name", SKILL_DIRS)
def test_skill_variables(skill_name):
    """Placeholders ⊆ canonical 4; no hardcoded paths."""
    skill_md = PLUGIN_ROOT / "skills" / skill_name / "SKILL.md"
    violations = _audit_skill(skill_md)
    assert not violations, f"skill {skill_name}: " + "; ".join(violations)


def test_dispatcher_template_canonical_superset():
    """Variables injected by the dispatcher template must be a superset of the canonical 4."""
    tpl = PLUGIN_ROOT / "framework" / "references" / "prompts" / "stage-subagent.md.tpl"
    text = tpl.read_text(encoding="utf-8")
    placeholders = set(PLACEHOLDER_PATTERN.findall(text))
    missing_canonical = CANONICAL_VARS - placeholders
    assert not missing_canonical, (
        f"dispatcher template missing canonical variables: {sorted(missing_canonical)}; "
        f"actual placeholders: {sorted(placeholders)}"
    )
