#!/usr/bin/env python3
"""sim bootstrap — deploy the simulation templates into a run workdir, then optionally render the UVM scaffold.

Behavior-preserving port of the former bootstrap shell (campaign §3.3): shutil.copytree +
str.replace do the `cp -a` + `sed -i` work (str.replace has no sed-delimiter hazard — the
MY_RTL_DIR / MY_SPEC_DIR values carry '..' path segments). Collapses the former three-script
pipeline into one verb: deploy infra, substitute the MY_* placeholders, infer TOP, rewrite
rtl_filelist.f (sim._filelist), and — when --scaffold is given — render the full UVM scaffold
via sim.scaffold.render (the same code path the standalone render-scaffold verb uses).

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed (infra only, or infra + scaffold)
  1  fail-closed guard (missing infra template dir / cannot infer top / missing RTL filelist /
     already-deployed workdir / missing --scaffold file)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# This file: skills/simulation/scripts/sim/bootstrap.py
#   parents[2] = skills/simulation   (-> templates/)
#   parents[4] = repo root           (-> asic/<module>/...)
_HERE = Path(__file__).resolve()
_TEMPLATE_DIR = _HERE.parents[2] / "templates"
_REPO_ROOT = _HERE.parents[4]

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


def infer_top_from_readme(rtl_dir: Path) -> str | None:
    """First non-table line naming a top module -> first identifier after ':'/'：'.
    Port of the shell's infer_top_from_readme (grep + sed). A ':' or '：' is REQUIRED; the
    producer always emits the cross-stage contract form `**Top module**: <top>`. First match
    wins; a first match that yields no valid identifier returns None (shell head -1 parity)."""
    f = rtl_dir / "README.md"
    if not f.is_file():
        return None
    line_re = re.compile(r"(^|[*#\s])(top|top\s+module)", re.I)
    extract_re = re.compile(r"^[^:：]*[:：]\s*([A-Za-z0-9_]+)")
    for raw in f.read_text(errors="replace").splitlines():
        line = raw.replace("\r", "")
        if re.match(r"^\s*\|", line):  # skip markdown table rows
            continue
        if not line_re.search(line):
            continue
        m = extract_re.match(line)
        if not m:
            return None
        top = m.group(1)
        return top if _IDENT_RE.match(top) else None
    return None


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
        base = os.path.basename(line.strip())
        for ext in (".v", ".sv", ".vh"):
            if base.endswith(ext):
                base = base[: -len(ext)]
        return base if _IDENT_RE.match(base) else None
    return None


def run(module: str, workdir, top: str | None = None, scaffold=None) -> int:
    infra = _TEMPLATE_DIR / "infra"
    if not infra.is_dir():
        _err(f"missing infra template directory: {infra}")
        return 1

    # Resolve workdir to absolute against the REPO ROOT (not cwd) + drop trailing slash.
    dest = Path(workdir)
    if not dest.is_absolute():
        dest = _REPO_ROOT / dest
    dest = Path(str(dest).rstrip("/"))

    rtl_dir = _REPO_ROOT / "asic" / module / "Design" / "rtl-design"
    spec_dir = _REPO_ROOT / "asic" / module / "Design" / "specification"
    rtl_filelist = rtl_dir / "filelist.txt"

    # workdir -> rtl-design / specification relpaths so env.sh / rtl_filelist.f stay portable
    # regardless of workdir depth (os.path.relpath matches the shell's python3 -c relpath).
    rtl_rel = os.path.relpath(rtl_dir, dest)
    spec_rel = os.path.relpath(spec_dir, dest)

    # Infer TOP (README first, then filelist) BEFORE the prereq/guard (shell order).
    if not top:
        top = infer_top_from_readme(rtl_dir)
    if not top:
        top = infer_top_from_filelist(rtl_dir)
    if not top:
        _err("cannot infer top-module name; pass --top <name>")
        return 1

    # Prerequisite: the rtl-design filelist must exist (the scaffold's RTL source).
    if not rtl_filelist.is_file():
        _err(f"missing RTL filelist: {rtl_filelist}")
        return 1

    # Overwrite guard: a caller may pre-create the workdir with hint files
    # (orchestrator-context.md etc.); only treat it as already-deployed when Makefile is present.
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "Makefile").is_file():
        _err(f"infra already deployed (detected {dest / 'Makefile'})")
        _err(
            "  To re-render the scaffold, use the render-scaffold verb, or hand a fresh empty workdir."
        )
        return 1

    # Step 1: deploy infra (cp -a templates/infra/. DEST) -> copytree into existing dir.
    shutil.copytree(infra, dest, dirs_exist_ok=True)
    for d in _UVM_SUBDIRS:
        (dest / "tb" / "uvm" / d).mkdir(parents=True, exist_ok=True)
    (dest / "tests").mkdir(parents=True, exist_ok=True)

    # Substitute MY_* across every deployed file carrying one (str.replace — no sed-delimiter
    # hazard for the '..'-bearing relpaths).
    repl = {
        "MY_TOP": top,
        "MY_MODULE": module,
        "MY_RTL_DIR": rtl_rel,
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

    # Step 2: rewrite rtl_filelist.f from Design/rtl-design/filelist.txt (paths rebased to rtl_rel).
    from sim._filelist import rewrite_rtl_filelist

    rewrite_rtl_filelist(rtl_filelist, dest / "rtl_filelist.f", rtl_rel)

    # Step 3: render the UVM scaffold when --scaffold is provided (same path as render-scaffold).
    if scaffold:
        scaffold_path = Path(scaffold)
        if not scaffold_path.is_absolute():
            scaffold_path = _REPO_ROOT / scaffold_path
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
