#!/usr/bin/env python3
"""Select tests from testlist.json by mode.

Output: one pipe-delimited row per selected test:
    {test_id}|{uvm_testname}

- smoke   -> tests whose suites[] contains "smoke"
- regress -> tests whose suites[] contains "regress" or "smoke"

Exits 2 when nothing is selected; the caller reads stdout on exit 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: select_tests.py <mode> <testlist-path>", file=sys.stderr)
        return 2
    mode, testlist_path = sys.argv[1:3]
    tests = json.loads(Path(testlist_path).read_text(encoding="utf-8")).get("tests", [])
    selected = []
    for t in tests:
        suites = t.get("suites", [])
        if mode == "smoke" and "smoke" in suites:
            selected.append(t)
        elif mode == "regress" and ("regress" in suites or "smoke" in suites):
            selected.append(t)
    if not selected:
        return 2
    for t in selected:
        print("{test_id}|{uvm_testname}".format(**t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
