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
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

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
        data = json.loads(_cache_path(module_root).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    # Pure speed cache (§1.1/§5.1): valid JSON of the wrong shape (list/scalar root) is
    # corruption — recompute, never crash. Per-entry shape is checked at the hit site.
    return data if isinstance(data, dict) else {}


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
    # A well-formed entry is [size, mtime_ns, fp] (what we write below); anything else
    # is corruption — fall through to recompute rather than IndexError/TypeError (§5.1).
    if (
        isinstance(hit, list)
        and len(hit) == 3
        and hit[0] == key[0]
        and hit[1] == key[1]
    ):
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
    lines = [ln for ln in (ln.strip() for ln in p.read_text().splitlines()) if ln]
    out = []
    for i, line in enumerate(lines):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break  # tolerate ONLY a truncated LAST line (spec §5.1)
            # A corrupt line mid-log would silently drop events (e.g. a dispatch -> run-
            # number reuse). Fail loud instead — never proceed on a corrupt append-only log.
            sys.exit(
                f"read_events: corrupt line {i + 1} of {p} "
                "(only a truncated last line is tolerated, spec §5.1)"
            )
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


_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"
_ENVELOPE_SCHEMA_PATH = (
    _PLUGIN_ROOT / "framework" / "references" / "schemas" / "envelope.schema.json"
)


def _stage_result_schema_path(rule_name: str) -> Path:
    """The rule's own result.schema.json, resolved from its skill name
    (`veripower:<dir>` -> skills/<dir>/references/result.schema.json)."""
    skill_dir = rules.RULES[rule_name].skill.split(":", 1)[1]
    return _PLUGIN_ROOT / "skills" / skill_dir / "references" / "result.schema.json"


def validate_result(rule_name: str, result: dict) -> str | None:
    """Validate a parsed result.json against the rule's per-stage schema (which
    $refs the shared result envelope). Returns None when valid, else the first
    violation message. Read-only and side-effect-free; infrastructure failure
    (missing/corrupt schema) is returned as a message too — the conservative
    direction is 'not proven valid', never a silent pass."""
    try:
        stage_schema = json.loads(_stage_result_schema_path(rule_name).read_text())
        envelope = Resource.from_contents(
            json.loads(_ENVELOPE_SCHEMA_PATH.read_text()),
            default_specification=DRAFT202012,
        )
        registry = Registry().with_resource(_ENVELOPE_URI, envelope)
        validator = jsonschema.Draft202012Validator(stage_schema, registry=registry)
        errors = sorted(
            validator.iter_errors(result), key=lambda e: list(e.absolute_path)
        )
    except Exception as e:
        return f"schema validation internal error: {type(e).__name__}: {e}"
    if not errors:
        return None
    err = errors[0]
    path = "$" + "".join(
        f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path
    )
    return f"schema violation at {path}: {err.message}"


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


def _reopened_after(events: list[dict], oracle_ref: str, anchor_index: int) -> bool:
    """True iff a reopen of oracle_ref appears at/after `anchor_index`."""
    for i, e in enumerate(events):
        if i >= anchor_index and e["type"] == "reopen" and e["pin_ref"] == oracle_ref:
            return True
    return False


def _dispatch_index(events: list[dict], rule: str, run: int) -> int | None:
    """Event position of the (rule, run) dispatch — when this run actually executed.
    A re-reap appends a later OUTCOME but reuses this dispatch, so it anchors condition 3
    to execution time, not to the re-readable outcome position."""
    for i, e in enumerate(events):
        if e["type"] == "dispatch" and e["rule"] == rule and e["run"] == run:
            return i
    return None


def _live_pin_exists(events: list[dict], oracle_ref: str) -> bool:
    """True iff some pin of oracle_ref has NO later reopen — i.e. the oracle is currently
    (re-)endorsed. Mirrors kernel._graded's liveness (existence only; grade needs the record)."""
    for i, e in enumerate(events):
        if e["type"] == "pin" and e["oracle_ref"] == oracle_ref:
            if not any(
                r["type"] == "reopen" and r["pin_ref"] == oracle_ref
                for r in events[i + 1 :]
            ):
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
    # condition 3 (oracle trust): invalid iff the oracle was reopened after this RUN's
    # DISPATCH and has not since been re-pinned. Anchoring on the dispatch (execution time),
    # not the outcome position, closes the re-reap whitewash (F5): a bare re-reap re-lands the
    # outcome past a reopen but re-executes nothing and re-pins nothing, so it must not
    # resurrect the proof. Genuine recovery still validates — a fresh dispatch AFTER the reopen
    # post-dates it (reopened_after=False), and a re-pin leaves a live pin (second conjunct false).
    if rule.oracle:
        oref = proof["oracle"]["ref"]
        d_idx = _dispatch_index(events, proof_name, outcome["run"])
        anchor = d_idx if d_idx is not None else idx
        if _reopened_after(events, oref, anchor) and not _live_pin_exists(events, oref):
            return False
    return True


def stale_inputs(module: str, events: list[dict], rule: str) -> list[str]:
    """The recorded inputs of `rule`'s latest outcome whose version no longer matches
    disk — the kernel-computed "what changed since the last run" set a forward re-run
    consumes for scope (written to `<workdir>/changed-inputs.md` at dispatch, see
    kernel.cmd_dispatch). Reuses proof_valid's per-input comparison but COLLECTS the
    mismatches instead of short-circuiting on the first. Self-produced in∩out inputs
    (e.g. lint-cdc's own `scripts/waiver.tcl`) and PIPELINE_INPUTS are excluded — a
    hand-edited own-output is not an upstream scope change (mirrors schedule._added_inputs).
    Empty when the rule never produced an outcome (a first delivery) — the caller then
    falls to full scope. Read-only; stores nothing (NOT the retired per-skill classify-delta
    input_digest — this is a query over the input versions already recorded in the log)."""
    hit = _proof_outcome(events, rule)
    if hit is None:
        return []
    _, outcome = hit
    proof = next((p for p in outcome["proofs"] if p["name"] == rule), None)
    if proof is None:
        return []
    root = module_root(module)
    own_outputs = set(outcome.get("outputs", {}))
    changed: list[str] = []
    for path, recorded in proof.get("inputs", {}).items():
        if path in own_outputs or path in rules.PIPELINE_INPUTS:
            continue
        if not versions_match(recorded, fingerprint_cached(root / path, root)):
            changed.append(path)
    return changed


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
        # self-produced in∩out input (e.g. lint-cdc waiver.tcl): ALWAYS available (spec §2
        # 自产输入豁免). The rule regenerates it; a cold start has none; and it must NEVER
        # gate the rule's own dispatch. Editing or deleting it invalidates THIS rule's proof
        # via condition 4 (§1.3) — which is exactly what schedules the re-run. Requiring the
        # on-disk file to match the last recorded output here would re-lock the rule the
        # instant that proof invalidates: the self-lock the exemption exists to forbid
        # ("无 outcome 或文件缺失 = 冷启动，照常可派发", and an edited file no differently).
        return True
    outcome = latest_outcome(events, prod)
    if outcome is None:
        # Producer never ran -> no output version exists -> input UNAVAILABLE (spec §2:
        # 可用 iff 生产规则最新 outcome 的产出版本 == 当前磁盘指纹). Forward scheduling still
        # reaches the producer via step-2's closure expansion; and this stops a manual
        # dispatch of a consumer in a virgin module from recording an empty input table —
        # a vacuously-valid proof forever (F7).
        return False
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
