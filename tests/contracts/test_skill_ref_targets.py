"""Resolve `module.symbol` and `<doc> §section` references inside every SKILL.md.

Companion to `test_skill_path_references.py`, which checks that backtick **file
paths** exist on disk. This lint catches the two reference classes that one
misses — and that the 2026-06-10 audit found broken (B1: `state.py._RESULT_DIR`,
a symbol that lives in `topology.py`; B2: `<child>.md §1.7+`, a section that
does not exist — a child sub-design is §1–§5):

  A. **module.symbol** — a backtick ref like `topology._RESULT_DIR` /
     `state._result_path` must name a symbol defined at module level in
     `framework/scripts/<module>.py`.

  B. **`<doc> §section`** — a doc-prefixed section ref must resolve to a real
     heading in that doc's static source. Runtime artifacts resolve via their
     template (`design.md`→design-template, `<child>.md`→child-design-template);
     static docs (ARCHITECTURE.md, CLAUDE.md, docs/*.md, …) resolve directly.

**Scope (deliberate):** only references that are *deterministically resolvable*
are checked. Bare section refs (`§1.6` with no doc prefix) are ambiguous about
their target doc → skipped. `verification-plan.md §n` has no static section
source in-repo → skipped. This keeps the lint a reliable signal with no false
positives; it is conservative by design, not exhaustive.
"""

import ast
import re

from _skills_sot import PLUGIN_ROOT, SKILL_DIRS

# ── module.symbol ────────────────────────────────────────────────────────
_MODULES = sorted(p.stem for p in (PLUGIN_ROOT / "framework" / "scripts").glob("*.py"))
_MOD_RE = re.compile(
    r"`(" + "|".join(_MODULES) + r")(?:\.py)?\.([A-Za-z_][A-Za-z0-9_]*)"
)
_MODULE_NAMES: dict[str, set[str]] = {}


def _module_attrs(module: str) -> set[str]:
    """Top-level names a `module.X` ref can resolve to — defs, classes,
    assignments, AND imported names (e.g. state.py re-exposes topology's
    `_result_path` via `from topology import …`). Static AST parse, no execution."""
    if module not in _MODULE_NAMES:
        tree = ast.parse(
            (PLUGIN_ROOT / "framework" / "scripts" / f"{module}.py").read_text()
        )
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    names.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update(a.asname or a.name for a in node.names)
        _MODULE_NAMES[module] = names
    return _MODULE_NAMES[module]


def _symbol_defined(module: str, symbol: str) -> bool:
    return symbol in _module_attrs(module)


# ── <doc> §section ───────────────────────────────────────────────────────
# Doc token → static source that defines its section structure.
_DOC_SOURCES = {
    "<child>.md": "skills/specification/references/child-design-template.md",
    "design.md": "skills/specification/references/design-template.md",
    "ARCHITECTURE.md": "ARCHITECTURE.md",
    "CLAUDE.md": "CLAUDE.md",
    "CONTRIBUTING.md": "CONTRIBUTING.md",
    "README.md": "README.md",
}
# Doc tokens with no static section source → not resolvable, skip.
_SKIP_DOCS = {"verification-plan.md", "result.json", "task.json", "events.jsonl"}

# doc (optionally backticked, optionally a path) immediately followed by §section
_SEC_RE = re.compile(r"([\w./<>-]+\.md)`?\s*§\s*([0-9][0-9.]*\+?)")


def _heading_lines(path) -> list[str]:
    return [ln for ln in path.read_text().splitlines() if re.match(r"^#{1,6}\s", ln)]


def _section_present(headings: list[str], sec: str) -> bool:
    sec = sec.rstrip("+").rstrip(".")
    # section label at a heading boundary; (?![\d.]) stops §1.6 matching "1.6.1"
    pat = re.compile(r"(?:^|\s|§|\()" + re.escape(sec) + r"(?![\d.])")
    return any(pat.search(h) for h in headings)


def _resolve_doc_source(doc: str):
    if doc in _SKIP_DOCS:
        return None
    if doc in _DOC_SOURCES:
        return PLUGIN_ROOT / _DOC_SOURCES[doc]
    if "/" in doc:  # a repo-relative path like docs/skill-structure-design.md
        p = PLUGIN_ROOT / doc
        return p if p.is_file() else None
    return None  # bare unknown doc → skip


def test_skill_module_symbol_refs_resolve() -> None:
    bad: list[str] = []
    checked = 0
    for skill in SKILL_DIRS:
        skill_md = PLUGIN_ROOT / "skills" / skill / "SKILL.md"
        if not skill_md.is_file():
            continue
        for mod, sym in _MOD_RE.findall(skill_md.read_text()):
            if (
                sym == "py"
            ):  # a bare `mod.py` file ref (extension, not a symbol) — path test owns it
                continue
            checked += 1
            if not _symbol_defined(mod, sym):
                bad.append(
                    f"{skill}/SKILL.md: `{mod}.{sym}` — no such symbol in {mod}.py"
                )
    assert checked, "regex matched no module.symbol refs — pattern likely broke"
    assert not bad, "Dead module.symbol references:\n  " + "\n  ".join(bad)


def test_skill_section_refs_resolve() -> None:
    bad: list[str] = []
    checked = 0
    for skill in SKILL_DIRS:
        skill_md = PLUGIN_ROOT / "skills" / skill / "SKILL.md"
        if not skill_md.is_file():
            continue
        for doc, sec in _SEC_RE.findall(skill_md.read_text()):
            src = _resolve_doc_source(doc)
            if src is None:
                continue  # not deterministically resolvable — skipped by design
            checked += 1
            if not _section_present(_heading_lines(src), sec):
                bad.append(
                    f"{skill}/SKILL.md: `{doc} §{sec}` — no matching heading in "
                    f"{src.relative_to(PLUGIN_ROOT)}"
                )
    assert checked, "regex matched no resolvable doc-prefixed §section refs"
    assert not bad, "Dead §section references:\n  " + "\n  ".join(bad)


def test_no_skill_reads_result_json_for_top_module():
    # Targeted: assert the exact read phrase is gone from the two migrated SKILLs.
    # (A whole-tree "contains both words" check would false-positive specification's
    # own SKILL, which legitimately documents producing top_module in its result.json.)
    for name in ("rtl-design", "simulation-plan"):
        text = (PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text()
        assert "stage_specific.top_module" not in text, (
            f"{name}: still reads top_module from result.json (use manifest.module)"
        )
