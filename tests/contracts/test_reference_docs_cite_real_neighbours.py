"""A contract or template cited by bare name must be a file that exists.

test_skill_path_references covers SKILL.md and only slash-bearing paths, because a bare
`design.md` is a runtime artifact that legitimately lives nowhere in the source tree. That
leaves the citations reference docs make to each other unchecked: renaming
check-hints contract broke one line in child-design-template.md and the whole suite
stayed green.

`-contract.md` and `-template.md` are the discriminator, and they need no exclusion list: every
reference doc shaped that way is source, and no runtime artifact is named that way. A doc that
is neither (attribution-rules.md, coverage-iteration.md) stays uncovered here rather than
dragging in a list of artifact names to subtract, which would be its own thing to keep current.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CITED = re.compile(r"`([a-z0-9][a-z0-9._-]*-(?:contract|template)\.md)`")
DOCS = sorted(ROOT.glob("skills/*/references/*.md")) + sorted(
    ROOT.glob("skills/*/SKILL.md")
)
KNOWN = {p.name for p in ROOT.glob("skills/*/references/*.md")}

assert DOCS and KNOWN, "no skill docs found; the glob moved"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT / "skills")))
def test_bare_contract_and_template_citations_exist(doc: Path) -> None:
    missing = sorted(
        {n for n in CITED.findall(doc.read_text(encoding="utf-8"))} - KNOWN
    )
    assert not missing, (
        f"{doc.relative_to(ROOT)} cites {missing}, which no references/ carries"
    )
