#!/usr/bin/env python3
"""sim bootstrap — deploy the simulation templates into a run workdir, then optionally render the UVM scaffold.

Deploy the infra templates without clobbering anything already there, substitute the MY_TOP
and MY_MODULE placeholders, generate rtl_filelist.f (sim._filelist) from the injected
absolute rtl-design root, and when --plan is given render the full UVM scaffold via
sim.scaffold.render.

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed (infra only, or infra + scaffold; rework when a carried Makefile is
     already present in workdir, first run otherwise — the no-clobber deploy never
     overwrites a carried TB)
  1  fail-closed guard (missing infra template dir / unusable top / missing RTL
     filelist / missing --plan sidecar)
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


def read_top(scaffold_dir) -> str:
    """The DUT top module name, indexed out of the `scaffold` input's tb-scaffold.json.

    Indexed rather than inferred: `top` is a required field of tb-scaffold.schema.json,
    validated by simulation-plan when it writes the file, and sim.scaffold indexes the same
    field a moment later to name <top>_tb_top.sv. A second source would let the MY_TOP
    substituted across the deployed infra disagree with the top the renderer emitted."""
    return json.loads((Path(scaffold_dir) / SCAFFOLD_NAME).read_text())["top"]


def _deploy_no_clobber(src_root: Path, dest: Path) -> list[Path]:
    """Copy every template file into dest unless dest already has one at that path: a file
    carried from the prior round always wins over the pristine template. Returns the files
    actually written."""
    written: list[Path] = []
    for p in src_root.rglob("*"):
        if p.is_dir() or "__pycache__" in p.parts:
            continue  # bytecode the test suite left beside the shipped scripts
        d = dest / p.relative_to(src_root)
        if d.exists():
            continue  # carried file — never overwrite
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, d)
        written.append(d)
    return written


def run(module: str, workdir, scaffold=None) -> int:
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

    top = read_top(inputs["scaffold"])
    if not _IDENT_RE.match(top):
        # The schema types `top` as a string without pinning its shape, so this is the one
        # place a name that cannot be a module identifier is reported. Left through, it
        # reaches VCS as a syntax error in generated code nobody wrote by hand.
        _err(f"{SCAFFOLD_NAME} `top` is not a Verilog identifier: {top!r}")
        return 1

    # A Makefile present means the prior round's TB was carried in before this verb ran:
    # a rework, not an abort. Absent means a first run.
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "Makefile").is_file():
        print(f"[sim bootstrap] rework — carried TB detected ({dest / 'Makefile'})")

    # Step 1: deploy infra, never over a file already there.
    deployed = _deploy_no_clobber(infra, dest)
    for d in _UVM_SUBDIRS:
        (dest / "tb" / "uvm" / d).mkdir(parents=True, exist_ok=True)
    (dest / "tests").mkdir(parents=True, exist_ok=True)

    # Substitute MY_TOP / MY_MODULE in what was just deployed, and only there. A carried file
    # had its placeholders substituted the round it was deployed, so re-reading it can only
    # find the literal text somewhere an author wrote it, and rewriting that would edit
    # carried work. Scanning the whole workdir instead would also mean reading every file the
    # tools left behind: on a real run directory that is 311 files and 56 MB, 170 of them
    # binary, to reach the three template files that actually carry a placeholder.
    repl = {"MY_TOP": top, "MY_MODULE": module}
    for path in deployed:
        text = path.read_text()
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

    # Step 3: render the UVM scaffold when --plan is provided.
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
