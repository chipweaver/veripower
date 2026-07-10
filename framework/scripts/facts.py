"""VeriPower facts — event I/O, content fingerprints, and freshness queries.

The sole durable state is asic/<module>/events.jsonl (append-only). Everything
else (freshness, projections, in-flight) is COMPUTED here by comparing recorded
input/output versions against current disk fingerprints. Bare-importable
(`import facts`); imports the rules registry."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).parent))
import rules  # noqa: E402,F401

UNKNOWN = "unknown"


def _hash_file(path: Path, h) -> None:
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)


def fingerprint(path: Path) -> str:
    """Content version. File -> sha256:<hex>; dir -> merkle:<hex> (sorted walk,
    symlink hashed by its target string, not followed). Missing/unreadable -> UNKNOWN."""
    try:
        if path.is_symlink():
            h = hashlib.sha256()
            h.update(b"symlink\0")
            h.update(os.readlink(path).encode())
            return "sha256:" + h.hexdigest()
        if path.is_dir():
            h = hashlib.sha256()
            entries = []
            for p in sorted(path.rglob("*"), key=lambda q: str(q.relative_to(path))):
                rel = str(p.relative_to(path))
                if p.is_symlink():
                    entries.append((rel, "L", os.readlink(p)))
                elif p.is_file():
                    fh = hashlib.sha256()
                    _hash_file(p, fh)
                    entries.append((rel, "F", fh.hexdigest()))
                # directories contribute only via their children's relpaths
            for rel, kind, payload in entries:
                h.update(f"{rel}\0{kind}\0{payload}\0".encode())
            return "merkle:" + h.hexdigest()
        if path.is_file():
            h = hashlib.sha256()
            _hash_file(path, h)
            return "sha256:" + h.hexdigest()
    except OSError:
        return UNKNOWN
    return UNKNOWN


def versions_match(recorded: str, current: str) -> bool:
    """True iff both are known and equal. UNKNOWN never matches (conservatively stale)."""
    return recorded == current and recorded != UNKNOWN and current != UNKNOWN


def _cache_path(module_root: Path) -> Path:
    return module_root / ".fingerprint-cache.json"


def _load_cache(module_root: Path) -> dict:
    try:
        return json.loads(_cache_path(module_root).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def fingerprint_cached(path: Path, module_root: Path) -> str:
    """fingerprint() with an mtime/size cache. Pure speed cache — never a fact source.

    Only regular non-symlink files are cached: resolve()/stat() follow symlinks,
    so caching a symlink would collide with its target's entry (and a symlink is
    one readlink to fingerprint anyway); a directory's own [size, mtime_ns] does
    not change when a nested file is edited, so a dir entry could go false-fresh."""
    try:
        if path.is_symlink() or not path.is_file():
            return fingerprint(path)
    except OSError:
        return fingerprint(path)
    try:
        rel = str(path.resolve().relative_to(module_root.resolve()))
    except ValueError:
        return fingerprint(path)
    cache = _load_cache(module_root)
    try:
        st = path.stat()
        key = [st.st_size, st.st_mtime_ns]
    except OSError:
        return fingerprint(path)
    hit = cache.get(rel)
    if hit and hit[0] == key[0] and hit[1] == key[1]:
        return hit[2]
    fp = fingerprint(path)
    if fp != UNKNOWN:
        cache[rel] = [key[0], key[1], fp]
        try:
            _cache_path(module_root).write_text(json.dumps(cache))
        except OSError:
            pass
    return fp


# Event log I/O

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_EVENT_SCHEMA_DIR = _PLUGIN_ROOT / "framework" / "references" / "schemas" / "events"


def module_root(module: str) -> Path:
    return Path("asic") / module


def events_path(module: str) -> Path:
    return module_root(module) / "events.jsonl"


def read_events(module: str) -> list[dict]:
    p = events_path(module)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a truncated line
    return out


def _event_schema(etype: str) -> dict:
    path = _EVENT_SCHEMA_DIR / f"{etype}.schema.json"
    if not path.exists():
        sys.exit(f"append_event: no schema for event type {etype!r}")
    return json.loads(path.read_text())


def append_event(module: str, event: dict, ts: str) -> None:
    etype = event.get("type")
    record = {"ts": ts, **event}  # ts first
    try:
        jsonschema.validate(record, _event_schema(etype))
    except jsonschema.ValidationError as e:
        sys.exit(f"append_event: {etype} schema violation: {e.message}")
    p = events_path(module)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def runs_of(events: list[dict], rule: str) -> int:
    return sum(1 for e in events if e["type"] == "dispatch" and e["rule"] == rule)


def in_flight(events: list[dict]) -> list[dict]:
    dispatched = [(e["rule"], e["run"]) for e in events if e["type"] == "dispatch"]
    reaped = {(e["rule"], e["run"]) for e in events if e["type"] == "outcome"}
    return [{"rule": r, "run": n} for (r, n) in dispatched if (r, n) not in reaped]


def latest_outcome(events: list[dict], rule: str) -> dict | None:
    for e in reversed(events):
        if e["type"] == "outcome" and e["rule"] == rule:
            return e
    return None
