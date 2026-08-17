#!/usr/bin/env python3
"""Reduce a `--output-format stream-json` transcript on stdin to the agent's own text.

Exits 3 on either sign that the subject was not isolated:

  * the init event still lists tools — isolation was never in place, and the run scores
    normally while measuring an agent that could have reached the repo. This is the silent
    form, and the one that actually bit: `--allowedTools ""` stopped disabling tools
    somewhere before CLI 2.1.233, so every tag stamped after that drifted away from the
    baseline it was compared against without anything looking wrong.
  * a `tool_use` block appears — a call landed despite the deny list.

Refusing to emit a tag is the point. A breached run is not a measurement, and a scenario
whose provenance mixes the two cannot be read at all.
"""

import json
import sys

text = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "system" and ev.get("subtype") == "init":
        tools = ev.get("tools") or []
        if tools:
            print(f"init still lists tools: {tools}", file=sys.stderr)
            raise SystemExit(3)
    elif ev.get("type") == "assistant":
        for block in ev.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                print(f"tool_use: {block.get('name')}", file=sys.stderr)
                raise SystemExit(3)
            if block.get("type") == "text":
                text.append(block["text"])
    elif ev.get("type") == "result" and not text:
        text.append(str(ev.get("result") or ""))

sys.stdout.write("\n".join(text))
