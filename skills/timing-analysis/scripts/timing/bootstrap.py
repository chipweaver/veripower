#!/usr/bin/env python3
"""Install missing tool setup from the dispatched inputs, preserving authored files."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# This file: skills/timing-analysis/scripts/timing/bootstrap.py
#   parents[2] = skills/timing-analysis   (-> templates/, ships with the skill)
# The kernel hands this verb an ABSOLUTE workdir, so nothing here depends on where it
# was launched from. A relative --workdir is still resolved against the CWD, for a
# human running the verb by hand from inside the module.
SCRIPT_PATH = Path(__file__).resolve()
TEMPLATE_DIR = SCRIPT_PATH.parents[2] / "templates"


def report_error(msg: str) -> None:
    print(f"[timing bootstrap] {msg}", file=sys.stderr)


def infer_top(syn_dir: Path) -> str | None:
    """Top inferred from the single Design/synthesis/out/<TOP>_syn.v (suffix
    '_syn.v' stripped). Returns the top when EXACTLY one matches; None on 0 or >1
    (a glob + count check — the caller then fails closed)."""
    cands = sorted((syn_dir / "out").glob("*_syn.v"))
    if len(cands) != 1:
        return None
    return cands[0].name[: -len("_syn.v")]


def run(workdir, top: str | None = None) -> int:
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if not TEMPLATE_DIR.is_dir():
        report_error(f"missing {TEMPLATE_DIR}")
        return 1

    # The design tree is the CWD (kernel.py + stage-subagent contract). Resolve a
    # relative workdir against it. type=Path already dropped any trailing slash.
    tree_root = Path.cwd()
    workdir = Path(workdir)
    if not workdir.is_absolute():
        workdir = tree_root / workdir

    # The synthesis stage root is injected into dispatch.json (dispatch-time), not
    # self-navigated via <module>/Design/synthesis.
    inputs = json.loads((workdir / "dispatch.json").read_text(encoding="utf-8"))[
        "inputs"
    ]
    syn_dir = Path(inputs["netlist"])  # synthesis stage root

    # Resolve TOP from the single out/<TOP>_syn.v when not given.
    if top is None:
        top = infer_top(syn_dir)
        if top is None:
            report_error(f"cannot infer top from {syn_dir}/out/*_syn.v; pass --top")
            return 1

    # Verify the canonical netlist + SDC the TCL reads.
    for f in (syn_dir / "out" / f"{top}_syn.v", syn_dir / "out" / f"{top}_syn.sdc"):
        if not f.is_file():
            report_error(f"missing external reference: {f}")
            return 1

    workdir.mkdir(parents=True, exist_ok=True)
    for source in TEMPLATE_DIR.rglob("*"):
        target = workdir / source.relative_to(TEMPLATE_DIR)
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    config = workdir / "config.tcl"
    if not config.exists():
        settings = {
            "TOP": top,
            "NETLIST_DIR": str(syn_dir),
            "LIB_DB": os.environ.get("LIB_DB"),
        }
        lines = [
            "# Tool configuration; supply the task's libraries and calculation settings."
        ]
        for key, value in settings.items():
            if value:
                literal = (
                    json.dumps(value, ensure_ascii=False)
                    .replace("$", "\\$")
                    .replace("[", "\\[")
                )
                lines.append(f"set {key} {literal}")
        config.write_text("\n".join(lines) + "\n")

    print(f"[timing bootstrap] deployed {workdir} (TOP={top})")
    return 0
