#!/usr/bin/env python3
"""sim check-materialization — env-exit completeness self-gate (thin-D1 presence only).

The env-build subagent gates its STATUS: DONE on this verb's exit code (no result.json write
here; finalize's full run remains the authoritative result.json verdict). Fails (exit 1) if any
required scaffold SV file is missing or any TODO marker survives in tb/uvm/**. Emits a trimmed
{unmaterialized, todo_residue} verdict on stdout; status truth is the exit code, not narration.
A thin-D1 fail maps to failure_phase=compile (this presence gate does not itself route conformance).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sim._gate import thin_d1
from sim._plan import load_plan


def run(workdir, plan_dir) -> int:
    workdir = Path(workdir).resolve()
    scaffold_doc = load_plan(plan_dir)
    d1_errs = thin_d1(workdir, scaffold_doc)
    verdict = {
        "unmaterialized": [e for e in d1_errs if "missing" in e],
        "todo_residue": [e for e in d1_errs if "TODO" in e],
    }
    print(
        json.dumps(verdict)
    )  # gate-class: exactly ONE verdict JSON line on stdout, both paths
    if d1_errs:
        # fix-message goes to STDERR only (keeps stdout a single parseable verdict line);
        # the env subagent gates STATUS: DONE on the exit code, not on stdout content.
        print(
            "check-materialization: materialization incomplete:\n  - "
            + "\n  - ".join(d1_errs)
            + "\nFill the scaffold (no TODO may survive; all required files present), then re-run. "
            "Budget-exhausted-with-residue -> failure_phase=compile.",
            file=sys.stderr,
        )
        return 1
    return 0
