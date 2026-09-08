"""Read the specification's check hints.

It is a function rather than a persisted copy: the result is the authored JSON, so writing it
out would leave a derived copy on disk for the next reader to pick up instead of the source.

check-scaffold's coverage matrix is its consumer; simulation reads the same file by check_id.
"""

from __future__ import annotations

import json
from pathlib import Path


class HintsError(Exception):
    """A malformed or missing check-hints.json."""


def load_check_hints(spec_workdir) -> list[dict]:
    """Every hint, in authored order.

    check_id is this function's key, so it is a precondition rather than a shape check: a
    reused one would collapse in a by-id map, making one testpoint appear to cover both and
    leaving the second silently unverified, and a missing one would drop out of the coverage
    matrix unnoticed. The file's shape is check-hints.schema.json's business, enforced where
    it is authored.
    """
    path = Path(spec_workdir) / "check-hints.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HintsError(f"{path} missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HintsError(f"{path} unreadable: {exc}") from exc
    seen: set[str] = set()
    for hint in doc:
        cid = hint.get("check_id")
        if not cid:
            raise HintsError(f"{path} has an entry without check_id")
        if cid in seen:
            raise HintsError(f"duplicate check_id {cid!r} in {path}")
        seen.add(cid)
    return doc
