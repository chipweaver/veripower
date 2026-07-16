"""CC-transcript token-usage parser (eval instrumentation).

Parses a Claude Code JSONL trace — either a Task subagent's mirrored
`.subagent_traces/<rule>-<id>.output` OR an orchestrator session
transcript `<sessionId>.jsonl` (same format) — and sums per-turn token
usage into one breakdown.

Streaming caveat: a single assistant message spans MULTIPLE lines
(partial -> final); each carries a `usage` object whose `output_tokens`
grows toward the final value while `input`/`cache_*` stay constant.
Summing raw lines double-counts. We dedup by `message.id`, keeping the
LAST line seen for each id (its output_tokens is complete).

Pure / read-only, stdlib only. Never raises: malformed lines are
skipped, a missing/empty file yields an all-zero breakdown. Consumed by
kernel.py (reap-time, per Task subagent trace) and
eval/aggregate/aggregate.py (session transcript). cost is audit-only and
never enters validity.

Invariant note: aggregate.py's total = task + mainthread relies on a
manifest contract — session_transcripts point at the orchestrator's own
<sessionId>.jsonl, which carries no sidechain (subagent) turns; those
live in separate mirrored files parsed only via the task-cost path.
"""

from __future__ import annotations

import json
from pathlib import Path

_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _empty() -> dict:
    out = {k: 0 for k in _TOKEN_KEYS}
    out["total_tokens"] = 0
    out["message_count"] = 0
    out["models"] = []
    return out


def parse_trace_usage(path) -> dict:
    """Sum token usage across a CC JSONL trace, deduping streaming lines
    by message.id (last line per id wins). Returns a breakdown dict with
    total_tokens = sum of the four token classes (pre-registered primary
    cost metric), message_count, and models (insertion-ordered). Never
    raises."""
    try:
        text = Path(path).read_text()
    except (OSError, ValueError):
        return _empty()

    last_by_id: dict[str, dict] = {}
    models: dict[str, None] = {}  # insertion-ordered set
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        u = msg.get("usage")
        mid = msg.get("id")
        if not isinstance(u, dict) or not mid:
            continue
        last_by_id[mid] = u  # keep last line seen for this message id
        model = msg.get("model")
        if model:
            models[model] = None

    out = {k: 0 for k in _TOKEN_KEYS}
    for u in last_by_id.values():
        for k in _TOKEN_KEYS:
            v = u.get(k)
            if isinstance(v, int):
                out[k] += v
    out["total_tokens"] = sum(out[k] for k in _TOKEN_KEYS)
    out["message_count"] = len(last_by_id)
    out["models"] = list(models)
    return out
