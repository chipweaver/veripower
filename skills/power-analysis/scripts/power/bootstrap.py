#!/usr/bin/env python3
"""power bootstrap — deploy the power-analysis templates into a run workdir.

Behavior-preserving deploy built from focused, unit-testable steps (campaign design
§3.3): shutil.copytree + str.replace do the `cp -R` + `sed -i` work (str.replace has
no sed-delimiter hazard on '/'-containing paths).

Deploys templates/ into the caller-provided workdir
(<module>/Verification/power-analysis/runs/<N>/). The upstream synthesis /
simulation / simulation-plan stage-root locations come from the injected
`<workdir>/dispatch.json` `inputs` table ("netlist" / "tb_env" / "scaffold"), not by
self-navigating <module>/Design|Verification/<stage> — power has no
"rtl" key (it never consumes rtl-design). TOP is inferred from the injected
netlist's out/*_syn.v (suffix '_syn.v' stripped, same mechanism as
timing.infer_top) when not given. Substitutes the MY_TOP / MY_MODULE / MY_SYN_OUT
/ MY_SIM_DIR / MY_PLAN_DIR placeholders in env.sh (the three *_DIR values are now
absolute — kernel dispatch injects absolute locations, so no relpath climb is
needed), then renders the initial UVM power tests by shelling out to the
DEPLOYED emit_power_tests.py (Tier-2 asset — shell-out-to-deployed, NOT a
python->python subprocess-main; it enforces the sim-plan->power cross-stage
contract and fails closed). Fail-closed on a missing template dir, an
un-inferrable top, a missing synthesis netlist / simulation TB filelist /
simulation-plan's sidecars, or an emit failure. Idempotency guard: aborts when
the workdir already has a Makefile.

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed
  1  fail-closed guard (missing template dir / cannot infer top / already deployed
     / missing netlist|TB filelist|scaffold-spec / emit_power_tests failed)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# This file: skills/power-analysis/scripts/power/bootstrap.py
#   parents[2] = skills/power-analysis   (-> templates/, ships with the skill)
# The kernel hands this verb an ABSOLUTE workdir, so nothing here depends on where it
# was launched from. A relative --workdir is still resolved against the CWD, for a
# human running the verb by hand from inside the module.
_HERE = Path(__file__).resolve()
_TEMPLATE_DIR = _HERE.parents[2] / "templates"


def _err(msg: str) -> None:
    print(f"[power bootstrap] {msg}", file=sys.stderr)


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

    # The design tree is the CWD (kernel.py + stage-subagent contract). Resolve a
    # relative workdir against it. type=Path already dropped any trailing slash.
    tree_root = Path.cwd()
    workdir = Path(workdir)
    if not workdir.is_absolute():
        workdir = tree_root / workdir
    dest = workdir

    dest.mkdir(parents=True, exist_ok=True)
    # Idempotency guard — a Makefile means a prior deploy (the workdir may be
    # pre-created by the caller with only hint files; only a Makefile is "deployed").
    if (dest / "Makefile").is_file():
        _err(f"already deployed (detected {dest / 'Makefile'})")
        return 1

    # The synthesis / simulation / simulation-plan stage roots are injected into
    # dispatch.json (dispatch-time), not self-navigated via
    # <module>/Design|Verification/<stage>. No "rtl" key — power
    # never consumes rtl-design.
    inputs = json.loads((dest / "dispatch.json").read_text(encoding="utf-8"))["inputs"]
    syn_out_dir = Path(inputs["netlist"]) / "out"
    sim_dir = Path(inputs["tb_env"])
    plan_dir = Path(inputs["scaffold"])

    # Infer TOP from the injected synthesis netlist when not given — out/<TOP>_syn.v
    # already encodes it, so power stays off rtl-design entirely. Exactly one match or
    # nothing: two netlists mean the run has no basis for choosing, and picking the
    # alphabetically first one analyses a design nobody asked about while reporting a
    # power_mw for it. --top is the caller's way out of that, not a way past it.
    if top is None:
        cands = sorted(syn_out_dir.glob("*_syn.v"))
        if len(cands) != 1:
            _err(
                f"cannot infer --top: {len(cands)} out/*_syn.v under {syn_out_dir}; "
                "pass --top explicitly"
            )
            return 1
        top = cands[0].name[: -len("_syn.v")]

    # Pre-flight: upstream stages must have produced their canonical artifacts before
    # we deploy anything. Run it BEFORE copytree so a missing upstream ref fails fast
    # without leaving a partial deploy — a deployed Makefile would otherwise trip the
    # idempotency guard on the user's retry ("already deployed"). Matches the other
    # three stage bootstraps (check before copy).
    syn_netlist = syn_out_dir / f"{top}_syn.v"
    sim_filelist = sim_dir / "filelist.f"
    plan_sidecars = [plan_dir / "sequences.json", plan_dir / "power-scenarios.json"]
    if not syn_netlist.is_file():
        _err(f"synthesis netlist not found: {syn_netlist}")
        return 1
    if not sim_filelist.is_file():
        _err(f"simulation TB filelist not found: {sim_filelist}")
        return 1
    for p in plan_sidecars:
        if not p.is_file():
            _err(f"simulation-plan sidecar not found: {p}")
            return 1

    # cp -R templates/. dest  (copy template CONTENTS into the workdir).
    shutil.copytree(_TEMPLATE_DIR, dest, dirs_exist_ok=True)

    # env.sh gets the injected stage roots as absolute paths — kernel dispatch
    # injects absolute locations, so env.sh stays correct regardless of workdir
    # depth without any relpath computation.
    _sub(
        dest / "env.sh",
        {
            "MY_TOP": top,
            "MY_MODULE": module,
            "MY_SYN_OUT": str(syn_out_dir),
            "MY_SIM_DIR": str(sim_dir),
            "MY_PLAN_DIR": str(plan_dir),
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
            str(plan_dir),
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
