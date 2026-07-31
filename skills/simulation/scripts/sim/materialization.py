#!/usr/bin/env python3
"""sim check-materialization — the env-build child's own exit gate.

That child gates its STATUS: DONE on this verb's exit code; it writes no result.json, and
finalize's run remains the authoritative verdict. Exit 1 when a required scaffold SV file is
missing or a TODO marker survives in tb/uvm/**, which the orchestrator records as
failure_phase=compile. Presence only: whether a check verifies the right thing is the
conformance review's question, not this one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sim._gate import materialization_errors
from sim._plan import load_plan


def run(workdir, plan_dir) -> int:
    workdir = Path(workdir).resolve()
    scaffold_doc = load_plan(plan_dir)
    errs = materialization_errors(workdir, scaffold_doc)
    verdict = {
        "unmaterialized": [e for e in errs if "missing" in e],
        "todo_residue": [e for e in errs if "TODO" in e],
    }
    print(
        json.dumps(verdict)
    )  # gate-class: exactly ONE verdict JSON line on stdout, both paths
    if errs:
        # fix-message goes to STDERR only (keeps stdout a single parseable verdict line);
        # the env subagent gates STATUS: DONE on the exit code, not on stdout content.
        print(
            "check-materialization: materialization incomplete:\n  - "
            + "\n  - ".join(errs)
            + "\nFill the scaffold (no TODO may survive; all required files present), then re-run. "
            "Budget-exhausted-with-residue -> failure_phase=compile.",
            file=sys.stderr,
        )
        return 1
    return 0
