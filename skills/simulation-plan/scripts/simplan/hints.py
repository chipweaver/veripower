"""Aggregate the per-child check hints out of a specification workdir.

The files are per-child because wave-2 children are authored in parallel; the aggregate is
global because check_id uniqueness and the coverage matrix are. It is a function rather than
a file: the result is a pure concatenation of authored JSON, so persisting it would leave a
derived copy on disk for the next reader to pick up instead of the source.

Both consumers — materialize-scaffold (inlined_check_hints[]) and check-scaffold (the
coverage matrix) — call this, so the uniqueness check runs once per invocation either way.
"""

from __future__ import annotations

import json
from pathlib import Path


class HintsError(Exception):
    """A malformed or missing per-child hint file."""


def load_check_hints(spec_workdir) -> list[dict]:
    """Every child's check-hints/<child>.json, in manifest order.

    check_id is this function's key, so it is a precondition rather than a shape check: a
    reused one would collapse in a by-id map, making one testpoint appear to cover both and
    leaving the second silently unverified, and a missing one would drop out of the coverage
    matrix unnoticed. The FILES' shape is check-hints.schema.json's business, enforced where
    they are authored.
    """
    root = Path(spec_workdir)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HintsError(f"{root / 'manifest.json'} unreadable: {exc}") from exc
    hints: list[dict] = []
    seen: dict[str, str] = {}
    for child in manifest["children"]:
        name = child.get("name")
        path = root / "check-hints" / f"{name}.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HintsError(
                f"{path} missing: every child authors its own check hints"
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise HintsError(f"{path} unreadable: {exc}") from exc
        for hint in doc:
            cid = hint.get("check_id")
            if not cid:
                raise HintsError(f"{path} has an entry without check_id")
            if cid in seen:
                raise HintsError(f"duplicate check_id {cid!r}: {seen[cid]} and {name}")
            seen[cid] = name
            hints.append(hint)
    return hints
