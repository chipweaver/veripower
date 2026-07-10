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


# Freshness: proof validity, input availability, projection


def _proof_outcome(events: list[dict], proof_name: str) -> tuple[int, dict] | None:
    """(position, outcome) of the latest outcome carrying proof_name. Position comes
    from enumerate, NEVER events.index (duplicate event lines would collide, and
    index() is O(n) per call)."""
    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        if e["type"] == "outcome" and any(p["name"] == proof_name for p in e["proofs"]):
            return i, e
    return None


def _reopened_after(events: list[dict], oracle_ref: str, proof_index: int) -> bool:
    """True iff a reopen of oracle_ref appears at/after the proof's outcome position."""
    for i, e in enumerate(events):
        if i >= proof_index and e["type"] == "reopen" and e["pin_ref"] == oracle_ref:
            return True
    return False


def proof_valid(module: str, events: list[dict], proof_name: str) -> bool:
    """spec §1.3: a proof is currently valid iff verdict==pass AND every recorded input
    version matches disk AND its oracle ref was not reopened after the proof landed AND
    every recorded output version matches disk (condition 4). in∩out inputs are compared
    against the same-run OUTPUT version, not the dispatch-time input version."""
    hit = _proof_outcome(events, proof_name)
    if hit is None:
        return False
    idx, outcome = hit
    proof = next(p for p in outcome["proofs"] if p["name"] == proof_name)
    if proof["verdict"] != "pass":
        return False
    root = module_root(module)
    rule = rules.RULES[proof_name]
    own_outputs = set(outcome.get("outputs", {}))
    # condition 2 (inputs) — in∩out handled by preferring the recorded output version
    for path, recorded in proof.get("inputs", {}).items():
        ref = (
            outcome["outputs"].get(path, recorded) if path in own_outputs else recorded
        )
        if not versions_match(ref, fingerprint_cached(root / path, root)):
            return False
    # condition 4 (own outputs, incl. canonical result.json)
    for path, recorded in outcome.get("outputs", {}).items():
        if not versions_match(recorded, fingerprint_cached(root / path, root)):
            return False
    # condition 3 (oracle not reopened after this proof landed)
    if rule.oracle and _reopened_after(events, proof["oracle"]["ref"], idx):
        return False
    return True


def _selector_paths(root: Path, glob: str) -> list[Path]:
    """Resolve a module-relative glob to existing paths (empty match = empty list)."""
    return sorted(root.glob(glob))


def input_available(
    module: str, events: list[dict], glob: str, *, consumer: str
) -> bool:
    import fnmatch

    if glob in rules.PIPELINE_INPUTS:  # external whitelist — need only exist
        return (module_root(module) / glob).exists()
    prod = rules.producer_of(glob)
    if prod is None:
        return False
    if prod == consumer:
        # self-produced in∩out input (e.g. lint-cdc waiver.tcl): compare against own
        # latest outcome's OUTPUT version; no outcome or no file = cold start, dispatchable
        # (never self-locks, spec §2 自产输入豁免).
        own = latest_outcome(events, consumer)
        if own is None:
            return True
        root = module_root(module)
        return all(
            versions_match(recorded, fingerprint_cached(root / path, root))
            for path, recorded in own.get("outputs", {}).items()
            if fnmatch.fnmatch(path, glob)
        )
    outcome = latest_outcome(events, prod)
    if outcome is None:
        return (
            True  # true cold start: producer never ran — forward will schedule it first
        )
    root = module_root(module)
    matched = False
    for path, recorded in outcome.get("outputs", {}).items():
        if fnmatch.fnmatch(path, glob):
            matched = True
            if not versions_match(recorded, fingerprint_cached(root / path, root)):
                return False
    if not matched and not _selector_paths(root, glob):
        # Producer HAS run yet nothing (recorded or on disk) matches this selector:
        # the input is genuinely absent. Vacuous-available here would dispatch the
        # consumer with a silently missing input — conservative direction is unavailable.
        return False
    prod_rule = rules.RULES[prod]
    if prod_rule.proof:
        return proof_valid(module, events, prod_rule.proof)
    return True


def rule_available(module: str, events: list[dict], rule_name: str) -> bool:
    rule = rules.RULES[rule_name]
    for globs in rule.inputs.values():
        for g in globs:
            if not input_available(module, events, g, consumer=rule_name):
                return False
    return True


def projection(module: str, events: list[dict]) -> dict[str, str]:
    """Per-stage cell per §4.4: valid | stale | failed | blocked | in-flight | missing.
    frontend-signoff renders by the §3.6 '已签核' predicate instead of its bare proof."""
    flying = {f["rule"] for f in in_flight(events)}
    cells: dict[str, str] = {}
    for rule_name in rules.FORWARD_PRIORITY:
        if rule_name in flying:
            cells[rule_name] = "in-flight"
            continue
        outcome = latest_outcome(events, rule_name)
        if outcome is None:
            cells[rule_name] = "missing"
            continue
        if outcome["verdict"] == "blocked":
            cells[rule_name] = "blocked"
            continue
        if outcome["verdict"] == "fail":
            cells[rule_name] = "failed"
            continue
        cells[rule_name] = (
            "valid" if proof_valid(module, events, rule_name) else "stale"
        )
    # signoff cell override: valid iff a signoff-objective frontend-signoff proof is
    # currently valid AND every stage proof is currently valid (§3.6 判定语).
    if cells["frontend-signoff"] == "valid":
        signed = _signoff_dispatch_was_signoff(events) and all(
            proof_valid(module, events, r) for r in rules.FORWARD_PRIORITY
        )
        if not signed:
            cells["frontend-signoff"] = "stale"
    return cells


def _signoff_dispatch_was_signoff(events: list[dict]) -> bool:
    hit = _proof_outcome(events, "frontend-signoff")
    if hit is None:
        return False
    _, outcome = hit
    for e in events:
        if (
            e["type"] == "dispatch"
            and e["rule"] == "frontend-signoff"
            and e["run"] == outcome["run"]
        ):
            return e.get("objective") == "signoff"
    return False
