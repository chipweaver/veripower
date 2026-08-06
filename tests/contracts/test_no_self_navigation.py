"""Static no-self-navigation guard (Task 17, spec §10 #5) — permanent regression
lock for the inject+carry refactor's core invariant: no skill or framework
script resolves a cross-stage location by constructing it itself. Every
cross-stage reference must instead come from this round's injected
`<workdir>/dispatch.json` (the one legitimate exception being the design-flow
Orchestrator, which has no injected dispatch.json of its own and drives the
whole tree directly via `kernel.py` CLI args — see the (d) allowlist below).

Four checks, in increasing strength:
  (a) the five self-navigation token classes (spec §8 table) are COMPLETELY
      gone from skills/ + framework/.
  (b) no cross-stage `parents[3]` climb remains in skills/ (same-stage
      self-location — a script resolving its OWN templates/ dir via
      `parent.parent` / `parents[1]` / `parents[2]` — is allowed and uses a
      different token, so it is not caught here).
  (c) no CODE construction of a "Design"/"Verification" cross-stage path
      segment, anywhere outside the one legitimate source: framework/scripts/
      rules.py's `Rule.workdir_root` / `Rule.inputs` declarations — the SSoT
      registry `store.write_dispatch` itself reads to compute the absolute
      stage roots it writes into dispatch.json.
  (d) no `Design/<stage>/` or `Verification/<stage>/` slash-path prefix
      survives in any skills/*/SKILL.md outside a small justified allowlist.

Two REAL leftovers surfaced during this migration that the original
(a)/(b)-only guard would have MISSED: a `tree_root/.../Design/specification`
code construction, and SKILL.md prose baking `Design/<stage>/` — motivating
(c) and (d).
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _grep(pattern, *paths, fixed=True):
    """Fixed-string (`-F`) grep by default — critical for a pattern like
    `parents[3]`: an UNESCAPED regex grep would treat `[3]` as a bracket
    expression (matching a lone '3', not the literal brackets) and silently
    never match real source, vacuously passing. `-F` avoids that whole class
    of self-defeating guards."""
    args = ["grep", "-rn"]
    if fixed:
        args.append("-F")
    args += ["--include=*.py", "--include=*.tcl", "--include=*.sh", pattern, *paths]
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT)


# ── (a) the five self-navigation token classes must be COMPLETELY gone ───────
def test_self_navigation_tokens_gone():
    for pat in (
        "import seed",
        "from . import seed",
        "../../../rtl-design",
        "os.path.relpath",
        "MY_MODULE_ROOT",
    ):
        r = _grep(pat, "skills", "framework")
        assert r.returncode == 1, f"leftover self-navigation ({pat}):\n{r.stdout}"


# ── (b) no cross-stage parents[3] climb in skills/ ────────────────────────────
def test_no_cross_stage_parents3_climb():
    # Same-stage self-location (a script resolving its OWN templates/ dir, e.g.
    # `_HERE.parents[2] / "templates"`, or collect_report.py's `parent.parent`)
    # is a DIFFERENT token than the literal 3-deep climb checked here, so it is
    # never matched and needs no exclusion.
    r = _grep("parents[3]", "skills")
    assert r.returncode == 1, f"leftover cross-stage parents[3] climb:\n{r.stdout}"


# ── (c) no CODE construction of a cross-stage "Design"/"Verification" segment ─
# The ONE legitimate source: framework/scripts/rules.py's Rule declarations
# (Rule.workdir_root=("Design", <stage>) / Rule.inputs={...: ("Design/...",)}).
# This is the SSoT registry — write_dispatch() itself reads it to compute the
# absolute stage roots written into dispatch.json. It is not a consumer
# bypassing injection; it is the declarative source injection is built from.
# The whole-file exclusion below is sound only because rules.py's tuples are
# DECLARATIVE data, not procedural path construction — if a future edit adds a
# procedural `"Design"` build (e.g. a helper that joins the segment itself)
# inside rules.py, this exclusion needs revisiting.
_RULES_PY = "framework/scripts/rules.py"


def test_no_code_cross_stage_path_construction():
    """A standalone quoted string token (`"Design"` / `'Design'` /
    `"Verification"` / `'Verification'`) is how real path-join code names a
    stage segment — `Path(x) / "Design" / stage`, `os.path.join(x, "Design",
    ...)`, `("asic", module, "Design")`. A human-readable message/help/comment
    string that merely CONTAINS "Design/..." as running prose (e.g. "Populate
    Design/rtl-design/filelist.txt with ...") never has "Design" flanked by its
    own quote pair, so it does not match this check — verified empirically
    against every such string in the corpus (see report)."""
    hits = []
    for tok in ('"Design"', "'Design'", '"Verification"', "'Verification'"):
        r = _grep(tok, "skills", "framework")
        for line in r.stdout.splitlines():
            if line.startswith(_RULES_PY + ":"):
                continue  # SSoT registry — see module docstring
            hits.append(line)
    assert not hits, (
        "cross-stage path CONSTRUCTION found outside the rules.py SSoT registry:\n"
        + "\n".join(hits)
    )


# ── (d) no cross-stage Design/<stage>/ or Verification/<stage>/ prefix in
#        skills/*/SKILL.md, outside a small justified allowlist ─────────────
# (file, 1-based line number) -> justification. Each entry inspected by hand.
_SKILL_MD_ALLOWLIST = {
    # advisory prose FORBIDDING the anti-pattern, not an instance of it.
    ("skills/simulation-triage/SKILL.md", 23): (
        "prose instructing the skill to NEVER construct such a path itself — "
        "the guard-rail statement, not a violation of it"
    ),
}


def test_no_skill_md_cross_stage_path_prefix():
    hits = []
    for tok in ("Design/", "Verification/"):
        r = subprocess.run(
            ["grep", "-rn", "-F", "--include=SKILL.md", tok, "skills"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        for line in r.stdout.splitlines():
            path, lineno, _rest = line.split(":", 2)
            if (path, int(lineno)) in _SKILL_MD_ALLOWLIST:
                continue
            hits.append(line)
    assert not hits, (
        "un-allowlisted cross-stage Design/<stage>/ or Verification/<stage>/ "
        "path prefix in SKILL.md:\n" + "\n".join(hits)
    )
