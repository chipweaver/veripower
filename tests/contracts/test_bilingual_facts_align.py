"""A bilingual pair may differ in every word, and in no fact.

VeriPower's user-facing documents are written natively in each language rather than
translated, so sentence-level comparison is meaningless — the two are supposed to read
differently. What may not differ is what they state: a command, a path, a file name, a flag,
a stage name. Those are language-neutral, and they are where drift hurts.

It had already happened. `ARCHITECTURE.zh.md` carried three of §6's four limits: the whole of
"versioning of the intent stops at the container's edge" was absent, so a Chinese reader was
never told that a symlink inside `intent/` is fingerprinted by its target path and not its
content — a shared spec can move under it invisibly.

The one legitimate divergence is a cross-link: each document points at its own language's
sibling, so `X.zh.md` is normalised to `X.md` before comparing.
"""

import re

import pytest
from _skills_sot import PLUGIN_ROOT

HEADING = re.compile(r"^#{2,3}\s+(.+)$", re.M)
BACKTICKED = re.compile(r"`([^`\n]+)`")
# A backticked span is language-neutral when it looks like a path, a flag, a command, or a
# bare lowercase identifier — not when it is a quoted phrase.
NEUTRAL = re.compile(r"[/.]|^--|^kernel|^\d")


def _pairs():
    for zh in sorted(PLUGIN_ROOT.rglob("*.zh.md")):
        en = zh.with_name(zh.name.replace(".zh.md", ".md"))
        if en.is_file():
            yield en, zh


def _sections(path):
    text = path.read_text(encoding="utf-8")
    marks = list(HEADING.finditer(text))
    return [
        (
            m.group(1).strip(),
            text[m.end() : (marks[i + 1].start() if i + 1 < len(marks) else len(text))],
        )
        for i, m in enumerate(marks)
    ]


def _facts(body):
    out = set()
    for span in BACKTICKED.findall(body):
        span = span.strip().replace(".zh.md", ".md")
        if NEUTRAL.search(span) or re.fullmatch(r"[a-z][a-z0-9_-]*", span):
            out.add(span)
    return out


PAIRS = list(_pairs())


def test_there_are_bilingual_pairs_to_check():
    assert PAIRS, "no *.zh.md sibling found — this guard is checking nothing"


@pytest.mark.parametrize("en,zh", PAIRS, ids=[p[1].name for p in PAIRS])
def test_same_sections(en, zh):
    e, z = [h for h, _ in _sections(en)], [h for h, _ in _sections(zh)]
    assert len(e) == len(z), (
        f"{zh.name} has {len(z)} sections against {en.name}'s {len(e)} — one language "
        f"gained or lost a section"
    )


@pytest.mark.parametrize("en,zh", PAIRS, ids=[p[1].name for p in PAIRS])
def test_same_facts_per_section(en, zh):
    drift = []
    for (eh, eb), (zh_h, zb) in zip(_sections(en), _sections(zh)):
        fe, fz = _facts(eb), _facts(zb)
        for only, where in ((sorted(fe - fz), en.name), (sorted(fz - fe), zh.name)):
            if only:
                drift.append(f"{eh} / {zh_h}: only in {where}: {', '.join(only)}")
    assert not drift, (
        f"{zh.name} states different facts than {en.name}:\n  " + "\n  ".join(drift)
    )
