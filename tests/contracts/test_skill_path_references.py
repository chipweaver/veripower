"""Semantic skill lint (D6, scoped): file-path references in SKILL.md exist.

Catches the drift class where a SKILL.md cites a reference file that has
been renamed, moved, or deleted. Three categories of paths are tested:

  - `references/<name>`              → resolves under this skill's own
                                       skills/<name>/references/
  - `framework/<path>`               → resolves from repo root
  - `skills/<other>/...`             → cross-skill ref, resolves from repo
                                       root (the cited path must exist
                                       wherever it points)

Deliberately excluded: bare names like `design.md`, `brainstorm.md`,
`result.json`, `scaffold-specification.json`, `verification-plan.md`,
`traceability.md`, `checklist.md`. These are runtime artifacts produced by
the pipeline — they don't (and shouldn't) exist in the source tree, so a
"does this file exist" check is meaningless.

Anchor-based and section-name-based checks (every `「X」` section reference
resolves to an H2 in the same file) deliberately deferred: bracket usage
in the corpus is too sparse and non-systematic to produce useful
diagnostics today. Reconsider when the bracket convention is tightened.
"""

import re

import pytest
from _skills_sot import PLUGIN_ROOT, SKILL_DIRS

# Match backtick-quoted paths that include a slash and a recognized extension.
# The slash filters out bare-name runtime artifacts (design.md, brainstorm.md,
# etc.) which legitimately live nowhere in the source tree.
_PATH_RE = re.compile(
    r"`(?:\$\{CLAUDE_SKILL_DIR\}/)?("
    r"references/[a-zA-Z0-9_./-]+"
    r"|framework/[a-zA-Z0-9_./-]+"
    r"|skills/[a-zA-Z0-9_./-]+"
    r")`"
)


def _resolve(skill_name: str, raw: str):
    """Return the absolute Path the raw citation should resolve to."""
    if raw.startswith("references/"):
        return PLUGIN_ROOT / "skills" / skill_name / raw
    # framework/... and skills/... are both repo-root-relative.
    return PLUGIN_ROOT / raw


@pytest.mark.parametrize("skill_name", SKILL_DIRS)
def test_path_references_resolve(skill_name: str) -> None:
    skill_md = PLUGIN_ROOT / "skills" / skill_name / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    missing: list[tuple[str, str]] = []
    for m in _PATH_RE.finditer(text):
        cited = m.group(1)
        target = _resolve(skill_name, cited)
        if not target.exists():
            missing.append((cited, str(target.relative_to(PLUGIN_ROOT))))

    assert not missing, (
        f"SKILL.md {skill_name}: file-path references that do not resolve — "
        + "; ".join(f"`{cited}` → {tgt} (not found)" for cited, tgt in missing)
    )


@pytest.mark.parametrize("skill_name", SKILL_DIRS)
def test_template_md_path_references_resolve(skill_name: str) -> None:
    tmpl_dir = PLUGIN_ROOT / "skills" / skill_name / "templates"
    if not tmpl_dir.is_dir():
        pytest.skip("no templates/ dir")
    missing: list[tuple[str, str, str]] = []
    for md in sorted(tmpl_dir.rglob("*.md")):
        for m in _PATH_RE.finditer(md.read_text(encoding="utf-8")):
            cited = m.group(1)
            target = _resolve(skill_name, cited)
            if not target.exists():
                missing.append(
                    (
                        str(md.relative_to(tmpl_dir)),
                        cited,
                        str(target.relative_to(PLUGIN_ROOT)),
                    )
                )
    assert not missing, (
        f"templates markdown in {skill_name}: unresolved path refs — "
        + "; ".join(f"{f}: `{c}` → {t}" for f, c, t in missing)
    )
