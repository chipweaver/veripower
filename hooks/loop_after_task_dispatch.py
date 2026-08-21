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

Every guard below returns rather than raises, so a shape it cannot read costs the reminder
and nothing else — the dispatch it follows has already run.
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


def main() -> None:
    data = json.load(sys.stdin)
    if not DISPATCH.search(data["tool_input"]["command"]):
        return
    # A Bash call that exits non-zero reports a string, not the envelope dict, and
    # `kernel.py` has one such exit: no module directory at the resolved path. It never
    # carries a dispatch return — an `ok: false` prints on exit 0.
    resp = data["tool_response"]
    if not isinstance(resp, dict):
        return
    # `kernel.py dispatch --help` is a documented call (SKILL.md sends the Orchestrator
    # there for flags) and prints usage, not an envelope.
    try:
        out = json.loads(resp["stdout"])
    except ValueError:
        return
    # `execution` comes from the dispatch's own return, never from a stage list kept here:
    # the registry is the kernel's to own, and a copy of it in a hook would be one more
    # thing that can disagree with it. A dispatch the kernel refused carries none at all.
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
