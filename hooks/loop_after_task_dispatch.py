#!/usr/bin/env python3
"""PostToolUse(Bash) hook: after a `task` dispatch, put the loop back in front of the
Orchestrator at the moment it has to act on it.

The rule already lives in design-flow's SKILL.md, and measurement says that is not enough:
the skill body enters the session ONCE, as a message near position 0, and by the time the
context is a few hundred thousand tokens deep the Orchestrator has stopped running the
protocol and started predicting what `decide` would have said. It predicts well — but a
prediction that is wrong loses the parallelism silently, with nothing in `events.jsonl` to
show for it.

Only `task` dispatches are addressed. After a `main-thread` one the Skill owns the rest of
the turn by construction, so there is nothing to say.

Fail-OPEN, the opposite of `ask_judgment_verbs.py`: that gate protects a trust boundary and
must not vanish on its own bug; this one is a reminder, and a broken reminder must not stop
a design flow.
"""

import json
import re
import sys

DISPATCH = re.compile(r"kernel\.py\s+dispatch\b")

REMINDER = (
    "veripower loop: `{rule}` run {run} is in flight and this turn is not over. "
    "Your next call is `kernel.py decide` — now, before reaping it and before "
    "reporting. Make it even when you expect YIELD."
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not DISPATCH.search(cmd):
        return
    # `execution` comes from the dispatch's own return, never from a stage list kept here:
    # the registry is the kernel's to own, and a copy of it in a hook would be one more
    # thing that can disagree with it.
    resp = data.get("tool_response")
    if isinstance(resp, dict):
        resp = resp.get("stdout") or resp.get("output") or ""
    try:
        out = json.loads(str(resp)[str(resp).index("{") :])
    except Exception:  # noqa: BLE001
        return
    if not out.get("ok") or out.get("execution") != "task":
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": REMINDER.format(
                        rule=out.get("rule"), run=out.get("run")
                    ),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
