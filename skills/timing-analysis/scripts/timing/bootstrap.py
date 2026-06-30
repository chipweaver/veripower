#!/usr/bin/env python3
"""timing bootstrap — deploy the timing-analysis templates into a run workdir.

Behavior-preserving deploy built from focused, unit-testable steps (campaign design
§3.3): shutil.copytree + str.replace do the `cp -a` + `sed -i` work (str.replace has
no sed-delimiter hazard on '/'-containing paths); json.loads reads the synthesis
result.json status inline. Far simpler than synthesis's bootstrap: no filelist, no
rtl_load generation, no relpath — timing substitutes only absolute paths.

Deploys templates/ into the caller-provided workdir
(asic/<module>/Design/timing-analysis/runs/<N>/), verifies the synthesis
prerequisite (result.json status=pass) and the netlist+SDC the TCL reads, resolves
TOP, and substitutes the MY_MODULE_ROOT / MY_WORKDIR (run_sta.tcl) and MY_TOP /
FILL_IN_LIB_DB_PATH (config.tcl) placeholders. Fail-closed on a missing/non-pass
synthesis, an un-inferrable top, or a missing external reference. Idempotency
guard: aborts when the workdir is already deployed.

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed
  1  fail-closed guard (missing template dir / synthesis result missing or not pass
     / cannot infer top / missing netlist or SDC / already deployed)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# This file: skills/timing-analysis/scripts/timing/bootstrap.py
#   parents[2] = skills/timing-analysis   (-> templates/, ships with the skill)
# The design tree (asic/<module>/...) is anchored on the CWD, NOT on where this code
# lives — matching state.py and the stage-subagent contract ("workdir is relative to
# the working tree root containing asic/").
_HERE = Path(__file__).resolve()
_TEMPLATE_DIR = _HERE.parents[2] / "templates"


def _err(msg: str) -> None:
    print(f"[timing bootstrap] {msg}", file=sys.stderr)


def infer_top(syn_dir: Path) -> str | None:
    """Top inferred from the single Design/synthesis/out/<TOP>_syn.v (suffix
    '_syn.v' stripped). Returns the top when EXACTLY one matches; None on 0 or >1
    (a glob + count check — the caller then fails closed)."""
    cands = sorted((syn_dir / "out").glob("*_syn.v"))
    if len(cands) != 1:
        return None
    return cands[0].name[: -len("_syn.v")]


def _read_status(syn_result: Path) -> str:
    """The synthesis result.json status (read via json.loads). Any read/parse
    failure -> '' -> the caller fails closed (non-pass)."""
    try:
        return json.loads(syn_result.read_text()).get("status", "")
    except (OSError, json.JSONDecodeError):
        return ""


def _sub(path: Path, placeholder: str, value: str) -> None:
    """In-place placeholder substitution (str.replace — no sed-delimiter hazard)."""
    path.write_text(path.read_text().replace(placeholder, value))


def run(module: str, workdir, top: str | None = None) -> int:
    if not _TEMPLATE_DIR.is_dir():
        _err(f"missing {_TEMPLATE_DIR}")
        return 1

    # The design tree is the CWD (state.py + stage-subagent contract). Resolve a
    # relative workdir against it. type=Path already dropped any trailing slash.
    tree_root = Path.cwd()
    workdir = Path(workdir)
    if not workdir.is_absolute():
        workdir = tree_root / workdir
    module_root_abs = tree_root / "asic" / module
    syn_dir = tree_root / "asic" / module / "Design" / "synthesis"

    # Prerequisite: synthesis result.json present and status=pass (fail-closed).
    syn_result = syn_dir / "result.json"
    if not syn_result.is_file():
        _err(f"missing {syn_result}")
        return 1
    status = _read_status(syn_result)
    if status != "pass":
        _err(f"synthesis result.json status={status} (need pass)")
        return 1

    # Resolve TOP from the single out/<TOP>_syn.v when not given.
    if top is None:
        top = infer_top(syn_dir)
        if top is None:
            _err(f"cannot infer top from {syn_dir}/out/*_syn.v; pass --top")
            return 1

    # Verify the canonical netlist + SDC the TCL reads.
    for f in (syn_dir / "out" / f"{top}_syn.v", syn_dir / "out" / f"{top}_syn.sdc"):
        if not f.is_file():
            _err(f"missing external reference: {f}")
            return 1

    workdir.mkdir(parents=True, exist_ok=True)
    if (workdir / "run_sta.tcl").is_file():
        _err(f"already deployed (detected {workdir / 'run_sta.tcl'})")
        return 1

    # cp -a templates/. workdir  (copy template CONTENTS into the existing workdir).
    shutil.copytree(_TEMPLATE_DIR, workdir, dirs_exist_ok=True)

    # Substitute placeholders (str.replace — paths contain '/', no sed hazard).
    _sub(workdir / "run_sta.tcl", "MY_MODULE_ROOT", str(module_root_abs))
    _sub(workdir / "run_sta.tcl", "MY_WORKDIR", str(workdir))

    # `... or X` (NOT `.get(k, X)`) falls back on unset OR empty. An
    # exported-but-empty LIB_DB must keep the placeholder, else config.tcl gets
    # `set LIB_DB ` (empty value) and result.read_lib_db's `\S+` regex no longer
    # matches. (Same idiom the ref#2 synthesis port uses.)
    lib_db_value = os.environ.get("LIB_DB") or "FILL_IN_LIB_DB_PATH"
    _sub(workdir / "config.tcl", "MY_TOP", top)
    _sub(workdir / "config.tcl", "FILL_IN_LIB_DB_PATH", lib_db_value)

    print(f"[timing bootstrap] deployed {workdir} (TOP={top}, LIB_DB={lib_db_value})")
    return 0
