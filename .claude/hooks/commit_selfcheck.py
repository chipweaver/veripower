#!/usr/bin/env python3
"""PreToolUse(Bash) hook: force a commit-message self-check against
CONTRIBUTING.md §Commit messages before any `git commit` lands.

Deterministic trigger (always fires on `git commit`), no format judgement and
no model call. It blocks the FIRST attempt for a given message, feeds the
convention + staged diff back to Claude so it re-reads its own message, then
allows the re-submit of the same message (one-shot gate keyed by the message,
not the command — the surrounding shell may vary). Revising the message re-arms
the gate, so each final message is checked once.

Fail-open: any internal error allows the command — a hook bug must never wedge
a legitimate commit.
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

TTL_SECONDS = 3600  # stale "already-checked" marker is re-armed after this


def commit_invoked(command: str) -> bool:
    """True if `command` runs a real `git commit` (not --dry-run/--help)."""
    try:
        toks = shlex.split(command)
    except ValueError:
        toks = command.split()
    takes_arg = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
    i = 0
    while i < len(toks):
        if toks[i] == "git" or toks[i].endswith("/git"):
            j = i + 1
            while j < len(toks) and toks[j].startswith("-"):
                if toks[j] in takes_arg:
                    j += 1
                j += 1
            if j < len(toks) and toks[j] == "commit":
                rest = toks[j + 1 :]
                if "--dry-run" in rest or "--help" in rest or "-h" in rest:
                    return False
                return True
        i += 1
    return False


def extract_message(command: str):
    """Best-effort commit message from `command`. Keys the one-shot gate on the
    message so surrounding shell (git add, &&, post-commit git log) can vary
    without re-arming. Returns None when no inline message is present (editor /
    `--amend --no-edit`) — nothing to self-check pre-hoc, so the caller allows.
    """
    # 1) heredoc body: -m "$(cat <<'EOF' ... EOF)" and friends
    bodies = [
        m.group(2)
        for m in re.finditer(
            r"<<-?\s*['\"]?(\w+)['\"]?\r?\n(.*?)\r?\n\1\b", command, re.DOTALL
        )
    ]
    if bodies:
        return "\n".join(bodies).strip()
    # 2) plain -m / --message values (shlex chokes on $(...) — handled above)
    try:
        toks = shlex.split(command)
    except ValueError:
        return None
    vals = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("-m", "--message") and i + 1 < len(toks):
            vals.append(toks[i + 1])
            i += 2
            continue
        if t.startswith("-m") and len(t) > 2:
            vals.append(t[2:])
        elif t.startswith("--message="):
            vals.append(t.split("=", 1)[1])
        i += 1
    return "\n\n".join(vals).strip() if vals else None


def staged_summary(project_dir: str) -> str:
    def run(args):
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return out.stdout.strip()
        except Exception:
            return ""

    stat = run(["diff", "--cached", "--stat"])
    if not stat:  # e.g. `git commit -a`: nothing in the index yet
        stat = run(["diff", "--stat"])
    if not stat:
        return "(no diff available)"
    if len(stat) > 4000:
        stat = stat[:4000] + "\n… (truncated)"
    return stat


REASON_TEMPLATE = """\
[commit-message self-check — CONTRIBUTING.md §Commit messages]

Inclusion test: write ONLY what a reader can't recover from a more
authoritative source. The diff records WHAT changed; CI records WHETHER it
passes. A message owns only what neither does.

- Subject: imperative, intent not mechanism, with a type: prefix
  (ci:/docs:/fix:/style:/…). A self-evident commit can stop at the subject.
- Body (only when warranted): the WHY — problem + root cause (cause only when
  non-obvious). No file:line evidence (the diff has it); length scales with the
  change.
- Verification: only checks CI does NOT run (manual bring-up, a local EDA flow,
  a reproduced bug). Never "pytest passes" — CI is the pass/fail record.
- Trailers: Co-authored-by, issue refs.

Staged changes for this commit:
{diff}

ACTION: re-read the message you just wrote against the test above.
- If it complies, re-run the SAME full command verbatim. The gate keys on the
  message, so any `git add` bundled into the command executes on this allowed
  pass — do NOT drop it on the re-run, or nothing will be staged.
- If not, revise the message and commit again.
"""


def allow():
    sys.exit(0)


def deny(reason: str):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def main():
    raw = sys.stdin.read()
    event = json.loads(raw)
    command = event.get("tool_input", {}).get("command", "")
    if not command or not commit_invoked(command):
        allow()

    message = extract_message(command)
    if not message:
        allow()  # editor-based / --amend --no-edit: no message to self-check here

    project_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    )

    key = hashlib.sha256(project_dir.encode()).hexdigest()[:16]
    state_path = os.path.join(tempfile.gettempdir(), f"claude-commit-selfcheck-{key}")
    msg_hash = hashlib.sha256(message.encode()).hexdigest()

    # Already prompted on this exact message recently → this is the re-submit.
    try:
        with open(state_path) as fh:
            seen_hash, seen_ts = fh.read().split()
        if seen_hash == msg_hash and (time.time() - float(seen_ts)) < TTL_SECONDS:
            os.remove(state_path)
            allow()
    except (FileNotFoundError, ValueError, OSError):
        pass

    try:
        with open(state_path, "w") as fh:
            fh.write(f"{msg_hash} {time.time()}")
    except OSError:
        allow()  # can't record state → don't risk a loop; let it through

    deny(REASON_TEMPLATE.format(diff=staged_summary(project_dir)))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail open: never wedge a legitimate commit on a hook bug.
        sys.exit(0)
