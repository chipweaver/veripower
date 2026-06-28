#!/usr/bin/env python3
"""power bootstrap — deploy the power-analysis templates into a run workdir.

Behavior-preserving deploy built from focused, unit-testable steps (campaign design
§3.3): shutil.copytree + str.replace do the `cp -R` + `sed -i` work (str.replace has
no sed-delimiter hazard on the '..'-containing relpaths); os.path.relpath computes the
three relpath values inline.

Deploys templates/ into the caller-provided workdir
(asic/<module>/Verification/power-analysis/runs/<N>/), infers TOP from the
rtl-design filelist, substitutes the MY_TOP / MY_MODULE / MY_SYN_OUT / MY_SIM_DIR
/ MY_PLAN_DIR placeholders in env.sh (the three *_DIR values are relpath(target,
workdir) so env.sh stays correct regardless of workdir depth), then renders the
initial UVM power tests by shelling out to the DEPLOYED emit_power_tests.py
(Tier-2 asset — shell-out-to-deployed, NOT a python->python subprocess-main; it
enforces the sim-plan->power cross-stage contract and fails closed). Fail-closed
on a missing template dir, an un-inferrable top, a missing synthesis netlist /
simulation TB filelist / scaffold-specification.json, or an emit failure.
Idempotency guard: aborts when the workdir already has a Makefile.

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed
  1  fail-closed guard (missing template dir / cannot infer top / already deployed
     / missing netlist|TB filelist|scaffold-spec / emit_power_tests failed)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# This file: skills/power-analysis/scripts/power/bootstrap.py
#   parents[2] = skills/power-analysis   (-> templates/)
#   parents[4] = repo root               (-> asic/<module>/...)
_HERE = Path(__file__).resolve()
_TEMPLATE_DIR = _HERE.parents[2] / "templates"
_REPO_ROOT = _HERE.parents[4]

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _err(msg: str) -> None:
    print(f"[power bootstrap] {msg}", file=sys.stderr)


def infer_top_from_filelist(rtl_dir: Path) -> str | None:
    """First true RTL path entry's basename (.v/.sv/.vh stripped) -> top, when an
    identifier. Skips comments (#), blanks, and +/- directives (the skip set is
    {#, blank, +/-} — NO '//' skip). Extensions are stripped sequentially (a name
    ending '.sv.v' loses both). This is the same filelist inference the synthesis
    stage uses."""
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


def _sub(path: Path, mapping: dict[str, str]) -> None:
    """In-place multi-placeholder substitution (str.replace — no sed-delimiter hazard
    on '/'-containing relpaths). One global pass over all keys; the five env.sh
    placeholders are mutually non-overlapping so replace order is irrelevant. The pass
    is global, so it also rewrites the MY_TOP/MY_MODULE mention inside the line-4
    comment."""
    text = path.read_text()
    for k, v in mapping.items():
        text = text.replace(k, v)
    path.write_text(text)


def run(module: str, workdir, top: str | None = None) -> int:
    if not _TEMPLATE_DIR.is_dir():
        _err(f"missing {_TEMPLATE_DIR}")
        return 1

    # Resolve workdir to absolute against the REPO ROOT (not cwd). type=Path already
    # dropped any trailing slash.
    workdir = Path(workdir)
    if not workdir.is_absolute():
        workdir = _REPO_ROOT / workdir
    dest = workdir

    dest.mkdir(parents=True, exist_ok=True)
    # Idempotency guard — a Makefile means a prior deploy (the workdir may be
    # pre-created by the caller with only hint files; only a Makefile is "deployed").
    if (dest / "Makefile").is_file():
        _err(f"already deployed (detected {dest / 'Makefile'})")
        return 1

    # Infer TOP from the rtl-design filelist when not given (fail-closed if unknown).
    if top is None:
        top = infer_top_from_filelist(
            _REPO_ROOT / "asic" / module / "Design" / "rtl-design"
        )
        if top is None:
            _err("cannot infer --top; pass explicitly")
            return 1

    syn_out_dir = _REPO_ROOT / "asic" / module / "Design" / "synthesis" / "out"
    sim_dir = _REPO_ROOT / "asic" / module / "Verification" / "simulation"
    plan_dir = _REPO_ROOT / "asic" / module / "Verification" / "simulation-plan"

    # Pre-flight: upstream stages must have produced their canonical artifacts before
    # we deploy anything. Run it BEFORE copytree so a missing upstream ref fails fast
    # without leaving a partial deploy — a deployed Makefile would otherwise trip the
    # idempotency guard on the user's retry ("already deployed"). Matches the other
    # three stage bootstraps (check before copy).
    syn_netlist = syn_out_dir / f"{top}_syn.v"
    sim_filelist = sim_dir / "filelist.f"
    plan_path = plan_dir / "scaffold-specification.json"
    if not syn_netlist.is_file():
        _err(f"synthesis netlist not found: {syn_netlist}")
        return 1
    if not sim_filelist.is_file():
        _err(f"simulation TB filelist not found: {sim_filelist}")
        return 1
    if not plan_path.is_file():
        _err(f"simulation-plan not found: {plan_path}")
        return 1

    # cp -R templates/. dest  (copy template CONTENTS into the workdir).
    shutil.copytree(_TEMPLATE_DIR, dest, dirs_exist_ok=True)

    # env.sh relpaths: relpath(target, workdir) so the env vars stay correct
    # regardless of workdir depth (canonical Verification/power-analysis/ vs runs/<N>/).
    _sub(
        dest / "env.sh",
        {
            "MY_TOP": top,
            "MY_MODULE": module,
            "MY_SYN_OUT": os.path.relpath(syn_out_dir, dest),
            "MY_SIM_DIR": os.path.relpath(sim_dir, dest),
            "MY_PLAN_DIR": os.path.relpath(plan_dir, dest),
        },
    )

    # Render the initial power tests via the DEPLOYED emit_power_tests.py (Tier-2).
    # It enforces the sim-plan->power cross-stage contract (power_scenarios[].sequence_ref
    # must resolve to sequences[].name + a non-empty agent) and exits 1 on violation;
    # its stderr surfaces verbatim (NOT captured) and we propagate the failure as exit 1
    # (fail closed). shell-out-to-deployed — allowed per design §3.3.
    rc = subprocess.run(
        [
            sys.executable,
            str(dest / "scripts" / "emit_power_tests.py"),
            "--plan",
            str(plan_path),
            "--module",
            module,
            "--out-dir",
            str(dest / "scaffold" / "power_tests"),
            "--filelist",
            str(dest / "scaffold" / "power_filelist.f"),
            "--top",
            top,
            "--test-tmpl",
            str(dest / "scaffold" / "power_test.sv.tmpl"),
        ]
    ).returncode
    if rc != 0:
        return 1  # emit_power_tests already printed the actionable cross-stage error

    print(f"[power bootstrap] deployed {dest} with TOP={top}")
    return 0
