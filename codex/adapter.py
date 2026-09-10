#!/usr/bin/env python3
"""Supply Codex execution instructions to the session and its subagents."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    event = json.load(sys.stdin)
    text = (ROOT / "codex/instructions.md").read_text().replace("@ROOT@", str(ROOT))
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
