"""Static acceptance for the B1 de-VeriPower EDA wrapper (P0 workstream (2)).

Wrapper content must be public, manual-level EDA tool usage only — no
VeriPower orchestration/gate/scaffold plumbing, no concrete module/design
fingerprints. These checks enforce that boundary without needing real EDA
tools (a smoke test that does need them is opportunistic, see Task 2).
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

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
    """Every stage target's OWN recipe lines must invoke a real EDA tool, not
    VeriPower plumbing. Checked against the target's own recipe only — not
    the whole scripts/ directory, whose comment headers name every tool and
    would make this vacuous for targets that merely dispatch to a script."""
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
    for t in _STAGE_TARGETS:
        body = " ".join(recipes.get(t, [])).lower()
        assert any(tool.lower() in body for tool in _BARE_TOOLS), (
            f"stage {t} recipe invokes no bare EDA tool"
        )


def test_demo_design_present():
    for rel in [
        "demo/rtl/accum.v",
        "demo/filelist.f",
        "demo/filelist.txt",
        "demo/tb/demo_tb.sv",
    ]:
        assert (WRAP / rel).is_file(), f"missing {rel}"


def test_readme_public_disclosure_and_provisions():
    readme = (WRAP / "README.md").read_text()
    low = readme.lower()
    # public-disclosure statement (manual-level, no VeriPower / no design)
    assert "manual" in low and ("public" in low or "no veripower" in low)
    # B1-provides checklist keywords
    for kw in ["rtl", "testbench", "constraint", "filelist"]:
        assert kw in low, f"README missing B1-provides item: {kw}"
    # explicit no-orchestration statement
    assert "orchestrat" in low or "you decide" in low or "no gate" in low


@pytest.mark.skipif(
    shutil.which("dc_shell") is None
    or not os.environ.get("LIB_DB")
    or not os.environ.get("UVM_HOME"),
    reason="no dc_shell / LIB_DB / UVM_HOME (EDA env absent)",
)
def test_smoke_synth_on_demo():
    """Opportunistic: if DC is installed, the demo must synthesize with the
    wrapper's own dc_run.tcl — proves the recipe actually drives the tool.
    FILELIST must be a manifest (one RTL path per line, dc_run.tcl's own
    contract) — demo/filelist.txt (RTL-only), not the bare RTL path.

    UVM_HOME is required here even though synthesis doesn't use UVM: `make
    synth` sources eval/b1-wrapper/env.sh, which hard-fails without it.

    Runs in a repo-internal tmpdir: some environments execute the EDA tools
    through a container that only allows a cwd under the repo root, so a
    /tmp workdir (pytest tmp_path) would never let the tool run."""
    parent = WRAP.parent  # eval/ — inside the repo
    work_root = tempfile.mkdtemp(prefix=".b1-smoke-", dir=str(parent))
    try:
        work = Path(work_root) / "b1"
        # Exclude build byproducts: a leftover out/accum_syn.v from a manual
        # `make synth` run inside WRAP (out/ is not gitignored) would
        # otherwise get carried into the fresh work copy and let the
        # existence assertion below pass even if this run's synth failed.
        shutil.copytree(
            WRAP,
            work,
            ignore=shutil.ignore_patterns(
                "out",
                "reports",
                "work",
                "spyglass_work",
                "cov_test*",
                "simv*",
                "csrc",
                "*.log",
                "*.vdb",
                "*.daidir",
            ),
        )
        env = {**os.environ, "TOP": "accum"}
        r = subprocess.run(
            ["make", "synth", "FILELIST=demo/filelist.txt"],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=1200,
        )
        assert r.returncode == 0, (
            "make synth failed:\n" + r.stdout[-2000:] + r.stderr[-2000:]
        )
        assert (work / "out" / "accum_syn.v").is_file(), (
            r.stdout[-2000:] + r.stderr[-2000:]
        )
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
