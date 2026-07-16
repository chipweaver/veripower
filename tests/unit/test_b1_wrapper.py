"""Static acceptance for the B1 de-VeriPower EDA wrapper (P0 workstream (2)).

Wrapper content must be public, manual-level EDA tool usage only — no
VeriPower orchestration/gate/scaffold plumbing, no concrete module/design
fingerprints. These checks enforce that boundary without needing real EDA
tools (a smoke test that does need them is opportunistic, see Task 2).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAP = ROOT / "eval" / "b1-wrapper"

# de-VeriPower: orchestration/gate/scaffold/result plumbing that only exists
# inside the pipeline.
_VERIPOWER_FORBIDDEN = [
    "result.json",
    "kernel.py",
    "scaffold-specification",
    "scaffold",
    "testlist.json",
    "inlined_check_hints",
    "_rm.sv",
    "IPD_STATUS",
    "IPD_TEST_ID",
    "collect_report",
    "parse_coverage",
    "emit_power",
]
# de-module: concrete design/module fingerprints that would leak the answer.
_MODULE_FORBIDDEN = [
    "fa_core_fsa",
    "softmax",
    "attention",
    "flash",
    "SS@125C",
    "TT@25C",
]

_STAGE_TARGETS = ["lint", "cdc", "synth", "sta", "sim-compile", "sim-run", "coverage"]
_BARE_TOOLS = ["spyglass", "dc_shell", "pt_shell", "vcs", "urg", "simv"]


def _wrapper_files():
    return [p for p in WRAP.rglob("*") if p.is_file()]


def test_wrapper_tree_exists():
    assert WRAP.is_dir(), f"{WRAP} missing"
    assert (WRAP / "Makefile").is_file()


def test_no_veripower_leakage():
    hits = []
    for p in _wrapper_files():
        try:
            text = p.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for pat in _VERIPOWER_FORBIDDEN:
            if pat in text:
                hits.append(f"{p.relative_to(ROOT)}: {pat}")
    assert not hits, "VeriPower plumbing leaked into wrapper:\n" + "\n".join(hits)


def test_no_module_leakage():
    hits = []
    for p in _wrapper_files():
        try:
            text = p.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for pat in _MODULE_FORBIDDEN:
            if pat.lower() in text.lower():
                hits.append(f"{p.relative_to(ROOT)}: {pat}")
    assert not hits, "Concrete module/design fingerprint leaked:\n" + "\n".join(hits)


def _makefile_targets():
    """Parse `target: prereqs` lines from the wrapper Makefile.
    Returns {target: [prereqs]} for non-.PHONY recipe targets."""
    out = {}
    for line in (WRAP / "Makefile").read_text().splitlines():
        m = re.match(r"^([a-zA-Z0-9_.-]+):(?!=)\s*(.*?)(?:\s*##.*)?$", line)
        if m and m.group(1) not in ("help",):
            out[m.group(1)] = m.group(2).split()
    return out


def test_makefile_stage_targets_are_flat():
    """Stage targets must not depend on OTHER stage targets — orchestration
    (which stage runs when) is what B1 is being measured on, not provided."""
    targets = _makefile_targets()
    for t in _STAGE_TARGETS:
        assert t in targets, f"missing target {t}"
        cross = [p for p in targets[t] if p in _STAGE_TARGETS]
        assert not cross, (
            f"target {t} depends on stage target(s) {cross} (must be flat)"
        )


def test_each_stage_recipe_invokes_a_bare_tool():
    """Every stage target's recipe (its lines + any script it calls) must
    invoke a real EDA tool, not VeriPower plumbing."""
    mk = (WRAP / "Makefile").read_text()
    # crude recipe extraction: lines after `target:` indented with a tab
    recipes, cur = {}, None
    for line in mk.splitlines():
        m = re.match(r"^([a-zA-Z0-9_.-]+):(?!=)", line)
        if m:
            cur = m.group(1)
            recipes[cur] = []
        elif cur and (line.startswith("\t")):
            recipes[cur].append(line)
    scripts_blob = " ".join(
        p.read_text() for p in (WRAP / "scripts").glob("*") if p.is_file()
    )
    for t in _STAGE_TARGETS:
        body = " ".join(recipes.get(t, [])) + " " + scripts_blob
        assert any(tool in body for tool in _BARE_TOOLS), (
            f"stage {t} recipe invokes no bare EDA tool"
        )
