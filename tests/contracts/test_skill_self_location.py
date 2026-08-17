"""Skills locate themselves through `<skill>`, never a harness variable.

`${CLAUDE_SKILL_DIR}` looks like an environment variable and is not one: it is
a render-time substitution Claude Code applies to a SKILL.md body, and only
there. The same literal in `references/*.md` — which Level-1 sub-Tasks are
handed and read as-is — reaches a shell unsubstituted and expands to the empty
string, turning a documented command into `python3 /scripts/...`. The rendered
body already carries the answer on its first line (`Base directory for this
skill: <abs path>`), so the variable bought nothing where it worked and broke
silently where it did not.

The corpus spells it `<skill>` instead: an angle-bracket placeholder like
`<key>` / `<scaffold>`, defined once per file and handed to every Level-1 child
that needs it.
"""

import re

import pytest
from _skills_sot import PLUGIN_ROOT, SKILL_DIRS

_HARNESS_VAR_RE = re.compile(r"\$\{?CLAUDE_[A-Z_]+")

# `<skill>/` and its path, up to the delimiters the corpus uses around one.
_SELF_REF_RE = re.compile(r"<skill>/([^\s`),]+)")


@pytest.mark.parametrize("skill_name", SKILL_DIRS)
def test_no_harness_variable_in_skill_tree(skill_name: str) -> None:
    offenders: list[str] = []
    for path in sorted((PLUGIN_ROOT / "skills" / skill_name).rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if _HARNESS_VAR_RE.search(line):
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}:{line_no}")

    assert not offenders, (
        f"{skill_name}: harness variable in skill content — write `<skill>`, "
        "and hand it to any Level-1 child that needs it: " + ", ".join(offenders)
    )


@pytest.mark.parametrize("skill_name", SKILL_DIRS)
def test_self_references_resolve(skill_name: str) -> None:
    """Every `<skill>/…` names something that exists in this skill."""
    skill_root = PLUGIN_ROOT / "skills" / skill_name
    files = [
        skill_root / "SKILL.md",
        *sorted(skill_root.glob("references/*.md")),
        *sorted(skill_root.glob("templates/**/*.md")),
    ]

    missing: list[str] = []
    for path in files:
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            for m in _SELF_REF_RE.finditer(line):
                cited = m.group(1).rstrip(".")
                # A second placeholder (`<skill>/../<stage>/templates/`) stands
                # for a set of paths, not one.
                if "<" in cited:
                    continue
                if not (skill_root / cited).exists():
                    missing.append(
                        f"{path.relative_to(PLUGIN_ROOT)}:{line_no} `<skill>/{cited}`"
                    )

    assert not missing, (
        f"{skill_name}: `<skill>/…` references that do not resolve — "
        + "; ".join(missing)
    )
