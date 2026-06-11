#!/usr/bin/env python3
"""Emit tab-separated <id>\\t<sequence_ref> rows from scaffold-specification.json's power_scenarios[].

Called by run_gls_power.sh to iterate scenarios. One row per scenario; empty
sequence_ref values become empty strings (not skipped — caller decides).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract_power_scenarios.py <plan-path>", file=sys.stderr)
        return 2
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    for s in plan.get("power_scenarios", []):
        print(f"{s.get('id', '')}\t{s.get('sequence_ref', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
