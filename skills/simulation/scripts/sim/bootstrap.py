#!/usr/bin/env python3
"""sim bootstrap — deploy the simulation templates into a run workdir, then optionally render the UVM scaffold.

Behavior-preserving port of the former bootstrap shell (campaign §3.3): a NO-CLOBBER
deploy (`_deploy_no_clobber`) + str.replace do the `cp -a` + `sed -i` work (str.replace
has no sed-delimiter hazard — the MY_RTL_DIR / MY_SPEC_DIR values carry '..' path
segments). Collapses the former three-script pipeline into one verb: deploy infra,
substitute the MY_* placeholders, infer TOP, rewrite rtl_filelist.f (sim._filelist), and
— when --scaffold is given — render the full UVM scaffold via sim.scaffold.render (the
same code path the standalone render-scaffold verb uses).

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed (infra only, or infra + scaffold; rework when a carried Makefile is
     already present in workdir, first run otherwise — the no-clobber deploy never
     overwrites a carried TB)
  1  fail-closed guard (missing infra template dir / cannot infer top / missing RTL
     filelist / missing --scaffold file)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

# This file: skills/simulation/scripts/sim/bootstrap.py
#   parents[2] = skills/simulation   (-> templates/, ships with the skill)
# The design tree (asic/<module>/...) is anchored on the CWD, NOT on where this code
# lives — matching kernel.py and the stage-subagent contract ("workdir is relative to
# the working tree root containing asic/").
_HERE = Path(__file__).resolve()
_TEMPLATE_DIR = _HERE.parents[2] / "templates"

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UVM_SUBDIRS = (
    "interface",
    "transaction",
    "agent",
    "checker",
    "refmodel",
    "env",
    "seq",
    "test",
    "pkg",
    "top",
)
_PLACEHOLDERS = ("MY_TOP", "MY_MODULE", "MY_RTL_DIR", "MY_SPEC_DIR")


def _err(msg: str) -> None:
    print(f"[sim bootstrap] {msg}", file=sys.stderr)


def infer_top_from_manifest(spec_dir: Path) -> str | None:
    """Top module name from the specification manifest (`manifest.module` — the authoritative
    structured source, spec §4.3; rtl-design / simulation-plan read the same field). Absent /
    unreadable / no `module` / non-identifier -> None (fall back to the RTL filelist). The
    manifest is read only for this coordinate — the top's freshness is absorbed by the tracked
    RTL fileset (§2⑦: a real top change necessarily changes RTL bytes), so simulation does NOT
    declare the manifest as an input."""
    f = spec_dir / "manifest.json"
    if not f.is_file():
        return None
    try:
        top = json.loads(f.read_text()).get("module")
    except (OSError, ValueError):
        return None
    return top if isinstance(top, str) and _IDENT_RE.match(top) else None


def infer_top_from_filelist(rtl_dir: Path) -> str | None:
    """First true RTL path entry's basename (.v/.sv/.vh stripped) -> top, when an identifier.
    Skips comments (#), blanks, and +/- directives. Extensions stripped sequentially."""
    f = rtl_dir / "filelist.txt"
    if not f.is_file():
        return None
    for raw in f.read_text(errors="replace").splitlines():
        line = raw.replace("\r", "")
        if re.match(r"^\s*#", line) or not line.strip() or re.match(r"^\s*[+\-]", line):
            continue
        base = os.path.basename(line)
        for ext in (".v", ".sv", ".vh"):
            if base.endswith(ext):
                base = base[: -len(ext)]
        return base if _IDENT_RE.match(base) else None
    return None


def _deploy_no_clobber(src_root: Path, dest: Path) -> None:
    """Copy every template file into dest UNLESS dest already has one at that path —
    a carried file (brought forward by kernel.py's carry_self before this verb runs,
    e.g. a prior round's TB) always wins over the pristine template."""
    for p in src_root.rglob("*"):
        if p.is_dir():
            continue
        d = dest / p.relative_to(src_root)
        if d.exists():
            continue  # carried file — never overwrite
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, d)


def run(module: str, workdir, top: str | None = None, scaffold=None) -> int:
    infra = _TEMPLATE_DIR / "infra"
    if not infra.is_dir():
        _err(f"missing infra template directory: {infra}")
        return 1

    # The design tree is the CWD (kernel.py + stage-subagent contract). Resolve a
    # relative workdir against it + drop trailing slash.
    tree_root = Path.cwd()
    dest = Path(workdir)
    if not dest.is_absolute():
        dest = tree_root / dest
    dest = Path(str(dest).rstrip("/"))

    # The rtl-design stage root is injected into inputs.json (dispatch-time), not
    # self-navigated via tree_root/asic/<module>/Design/rtl-design.
    inputs = json.loads((dest / "inputs.json").read_text(encoding="utf-8"))
    rtl_dir = Path(inputs["rtl"])
    spec_dir = tree_root / "asic" / module / "Design" / "specification"
    rtl_filelist = rtl_dir / "filelist.txt"

    # workdir -> specification relpath so env.sh's SPEC_DIR stays portable regardless
    # of workdir depth (os.path.relpath matches the shell's python3 -c relpath).
    # specification is NOT a declared input (rules.RULES["simulation"].inputs has no
    # "spec" key — manifest.module is read only for TOP inference, never a verdict-
    # dependency, see infer_top_from_manifest); RTL_DIR below is the absolute injected
    # rtl root instead.
    spec_rel = os.path.relpath(spec_dir, dest)

    # Infer TOP (manifest.module first — authoritative, spec §4.3 — then filelist) BEFORE
    # the prereq/guard. README is no longer consulted: manifest.module is the structured
    # source, and dropping the README read lets simulation stop declaring README as an input
    # (it was never a verdict-dependency — D6/G4).
    if not top:
        top = infer_top_from_manifest(spec_dir)
    if not top:
        top = infer_top_from_filelist(rtl_dir)
    if not top:
        _err("cannot infer top-module name; pass --top <name>")
        return 1

    # Prerequisite: the rtl-design filelist must exist (the scaffold's RTL source).
    if not rtl_filelist.is_file():
        _err(f"missing RTL filelist: {rtl_filelist}")
        return 1

    # Existence check: a caller may pre-create the workdir with hint files
    # (directive.md etc.). A Makefile present means carry_self already brought a
    # prior round's TB forward — treat as REWORK (the no-clobber deploy below never
    # overwrites it), not an abort; absent means a genuine first run.
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "Makefile").is_file():
        print(f"[sim bootstrap] rework — carried TB detected ({dest / 'Makefile'})")

    # Step 1: deploy infra NO-CLOBBER — a carried TB (carry_self, before this verb
    # runs) always wins over the empty infra template.
    _deploy_no_clobber(infra, dest)
    for d in _UVM_SUBDIRS:
        (dest / "tb" / "uvm" / d).mkdir(parents=True, exist_ok=True)
    (dest / "tests").mkdir(parents=True, exist_ok=True)

    # Substitute MY_* across every deployed file carrying one (str.replace — no sed-delimiter
    # hazard for the '..'-bearing relpaths).
    repl = {
        "MY_TOP": top,
        "MY_MODULE": module,
        "MY_RTL_DIR": str(rtl_dir),
        "MY_SPEC_DIR": spec_rel,
    }
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if any(ph in text for ph in _PLACEHOLDERS):
            for ph, val in repl.items():
                text = text.replace(ph, val)
            path.write_text(text)

    # chmod +x the deployed shell scripts (best-effort; shell did chmod +x scripts/*.sh).
    for sh in (dest / "scripts").glob("*.sh"):
        try:
            sh.chmod(sh.stat().st_mode | 0o111)
        except OSError:
            pass

    # Step 2: rewrite rtl_filelist.f from the injected rtl-design filelist.txt (paths
    # rebased to the ABSOLUTE rtl root). ALWAYS overwrites — a cross-stage-derived
    # filelist must re-anchor every round, so this is never no-clobbered.
    from sim._filelist import rewrite_rtl_filelist

    rewrite_rtl_filelist(rtl_filelist, dest / "rtl_filelist.f", str(rtl_dir))

    # Step 3: render the UVM scaffold when --scaffold is provided (same path as render-scaffold).
    if scaffold:
        scaffold_path = Path(scaffold)
        if not scaffold_path.is_absolute():
            scaffold_path = tree_root / scaffold_path
        if not scaffold_path.is_file():
            _err(f"missing scaffold-specification.json: {scaffold_path}")
            return 1
        from sim import scaffold as scaffold_mod

        scaffold_mod.render(
            scaffold_path, dest
        )  # default template dir = templates/scaffold
        print(f"[sim bootstrap] rendered UVM scaffold from {scaffold_path.name}")
    else:
        print("[sim bootstrap] --scaffold not supplied; deployed infra only.")

    print(f"[sim bootstrap] done — {dest}")
    print(f"  MODULE={module}  TOP={top}")
    return 0
