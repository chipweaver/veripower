#!/usr/bin/env python3
"""Add scheduling context after a background-stage dispatch."""

import json
import re
import sys

DISPATCH = re.compile(r"kernel\.py\s+dispatch\b")

REMINDER = (
    "veripower loop: after the executor for `{rule}` run {run} has started, "
    "call `kernel.py decide` to schedule other ready work."
)


def main() -> None:
    data = json.load(sys.stdin)
    if not DISPATCH.search(data["tool_input"]["command"]):
        return
    resp = data["tool_response"]
    if not isinstance(resp, dict):
        return
    try:
        out = json.loads(resp["stdout"])
    except ValueError:
        return
    if out.get("execution") != "task":
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": REMINDER.format(
                        rule=out["rule"], run=out["run"]
                    ),
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
