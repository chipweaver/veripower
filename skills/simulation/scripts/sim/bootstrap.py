#!/usr/bin/env python3
"""sim bootstrap — deploy the simulation templates into a run workdir, then optionally render the UVM scaffold.

Behavior-preserving port of the former bootstrap shell (campaign §3.3): a NO-CLOBBER
deploy (`_deploy_no_clobber`) + str.replace do the `cp -a` + `sed -i` work. Collapses
the former three-script pipeline into one verb: deploy infra, substitute the MY_TOP /
MY_MODULE placeholders, read TOP, generate rtl_filelist.f (sim._filelist) from the
injected absolute rtl-design root, and — when --scaffold is given — render the full
UVM scaffold via sim.scaffold.render (the same code path the standalone render-scaffold
verb uses).

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed (infra only, or infra + scaffold; rework when a carried Makefile is
     already present in workdir, first run otherwise — the no-clobber deploy never
     overwrites a carried TB)
  1  fail-closed guard (missing infra template dir / cannot read top / missing RTL
     filelist / missing --scaffold file)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from sim._plan import SCAFFOLD_NAME

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
_PLACEHOLDERS = ("MY_TOP", "MY_MODULE")


def _err(msg: str) -> None:
    print(f"[sim bootstrap] {msg}", file=sys.stderr)


def infer_top_from_scaffold(scaffold_dir: Path) -> str | None:
    """Top module name from the injected `scaffold` input's tb-scaffold.json
    (`top` — a REQUIRED field per its schema, skills/simulation-plan/references/
    tb-scaffold.schema.json). Absent / unreadable / no `top` / non-identifier
    -> None (fall back to the RTL filelist). Unlike the former specification/manifest.json
    read, `scaffold` IS a declared Rule.input (rules.RULES["simulation"].inputs["scaffold"]),
    so this coordinate's freshness is already covered by the kernel's own input-staleness
    check — no separate declaration needed."""
    f = scaffold_dir / SCAFFOLD_NAME
    if not f.is_file():
        return None
    try:
        top = json.loads(f.read_text()).get("top")
    except (OSError, ValueError):
        return None
    return top if isinstance(top, str) and _IDENT_RE.match(top) else None


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

    # The rtl-design / scaffold (simulation-plan) stage roots are injected into
    # dispatch.json (dispatch-time), not self-navigated via tree_root/asic/<module>/....
    inputs = json.loads((dest / "dispatch.json").read_text(encoding="utf-8"))["inputs"]
    rtl_dir = Path(inputs["rtl"])
    rtl_files_path = rtl_dir / "rtl-files.json"

    # Read TOP (the declared `scaffold` input's tb-scaffold.json `top` field —
    # a REQUIRED field, spec-input-contract) BEFORE the
    # prereq/guard. TOP comes from the scaffold: simulation does not declare specification
    # as an input, and `scaffold` already IS a declared one, so this is a coordinate the
    # stage genuinely tracks (mirrors power-analysis inferring TOP from its injected
    # netlist rather than a non-declared specification read).
    if not top:
        top = infer_top_from_scaffold(Path(inputs["scaffold"]))
    if not top:
        _err("cannot read top-module name; pass --top <name>")
        _err(f"  {SCAFFOLD_NAME} must carry a 'top' name.")
        return 1

    # Prerequisite: the rtl-design filelist must exist (the scaffold's RTL source).
    if not rtl_files_path.is_file():
        _err(f"missing RTL file list: {rtl_files_path}")
        return 1

    # Existence check: every fresh workdir already holds the kernel's dispatch.json.
    # A Makefile present means carry_self already brought a
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

    # Substitute MY_TOP / MY_MODULE across every deployed file carrying one (str.replace).
    repl = {
        "MY_TOP": top,
        "MY_MODULE": module,
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

    # Step 2: generate rtl_filelist.f from the injected rtl-files.json (paths anchored at
    # the ABSOLUTE rtl root). ALWAYS overwrites — a cross-stage-derived filelist must
    # re-anchor every round, so this is never no-clobbered.
    from sim._filelist import load_rtl_files, write_rtl_filelist

    write_rtl_filelist(load_rtl_files(rtl_dir), dest / "rtl_filelist.f", str(rtl_dir))

    # Step 3: render the UVM scaffold when --scaffold is provided (same path as render-scaffold).
    if scaffold:
        plan_dir = Path(scaffold)
        if not plan_dir.is_absolute():
            plan_dir = tree_root / plan_dir
        from sim import scaffold as scaffold_mod

        scaffold_mod.render(plan_dir, dest)  # default template dir = templates/scaffold
        print(f"[sim bootstrap] rendered UVM scaffold from {plan_dir}")
    else:
        print("[sim bootstrap] --plan not supplied; deployed infra only.")

    print(f"[sim bootstrap] done — {dest}")
    print(f"  MODULE={module}  TOP={top}")
    return 0
