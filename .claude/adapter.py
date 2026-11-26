#!/usr/bin/env python3
"""Supply native execution mappings and post-launch scheduling context."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMINDER = (
    "VeriPower: if you just launched a stage executor, "
    "call `kernel.py decide` now to schedule other ready work."
)


def main() -> None:
    event = json.load(sys.stdin)
    if event["hook_event_name"] == "PostToolUse":
        if event["tool_response"]["status"] not in (
            "async_launched",
            "remote_launched",
        ):
            return
        text = REMINDER
    else:
        text = (
            (ROOT / ".claude/instructions.md").read_text().replace("@ROOT@", str(ROOT))
        )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event["hook_event_name"],
                    "additionalContext": text,
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
