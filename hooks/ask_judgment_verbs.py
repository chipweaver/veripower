#!/usr/bin/env python3
"""PreToolUse(Bash) hook: prompt the human on every `kernel.py pin`, `reopen`,
and `signoff`.

These three are the judgment verbs: they are the only levers that move an
LLM-authored oracle across the proposed -> human trust line, and the only way a
module closes. The pipeline is allowed to *propose* them; only a human may let
one land. That gate has to travel with the plugin, because a plugin cannot ship
`permissions`: a plugin's own settings.json carries only `agent` and
`subagentStatusLine`. Left in the veripower repo's .claude/settings.json, the
gate would protect this repo and silently vanish for everyone who installs it.

Fail-ASK, not fail-open (the opposite of .claude/hooks/commit_selfcheck.py): a
gate whose job is to stop silent trust escalation must not disappear on its own
bug. The cost of the failure mode is one extra permission prompt.
"""

import json
import re
import sys

GATED = ("pin", "reopen", "signoff")

# The verb is the token right after kernel.py, whatever the path in front of it
# ("${CLAUDE_PLUGIN_ROOT}"/framework/scripts/kernel.py, a bare relative path, a
# `cd … && python3 …` compound).
_INVOCATION = re.compile(r"kernel\.py\s+([a-z]+)")
_HELP = re.compile(r"(?<!\S)(--help|-h)(?!\S)")

REASON = """\
veripower trust boundary: `kernel.py {verb}` is a judgment verb. It is what \
converts an LLM's own self-assessment into signoff-grade trust, so it is \
yours to make, not the agent's. Approve only if you intended this call.\
"""


def gated_verb(command: str) -> str | None:
    """The judgment verb `command` invokes, or None. `--help` is not a call."""
    for m in _INVOCATION.finditer(command):
        verb = m.group(1)
        if verb not in GATED:
            continue
        tail = re.split(r"[;|&]", command[m.end() :], maxsplit=1)[0]
        return None if _HELP.search(tail) else verb
    return None


def ask(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )


def main() -> None:
    try:
        event = json.load(sys.stdin)
        command = event.get("tool_input", {}).get("command", "")
        verb = gated_verb(command) if isinstance(command, str) else None
    except Exception as exc:
        ask(
            "veripower trust boundary: the ask-gate over `kernel.py "
            f"pin`/`reopen`/`signoff` could not read this command ({exc}). "
            "Asking rather than assuming it is safe."
        )
        return
    if verb:
        ask(REASON.format(verb=verb))
    # No output otherwise: defer to the normal permission flow.


if __name__ == "__main__":
    main()
    sys.exit(0)
