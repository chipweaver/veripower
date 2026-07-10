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
    """fingerprint() with an mtime/size cache. Pure speed cache — never a fact source."""
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
