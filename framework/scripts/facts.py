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


_LOADED: dict[str, dict] = {}


def _load_cache(module_root: Path) -> dict:
    """The module's cache dict, parsed from disk at most once per process.

    One `kernel.py status` calls fingerprint_cached ~80 times over ~40 distinct paths, so
    re-reading and re-parsing the whole file per call would cost more than the sha256 it
    saves on a small artifact, and half the calls repeat a path this process already hashed.
    The returned dict is the live one: fingerprint_cached's writes land here and are written
    through to disk, which is what lets the next process skip hashing a large netlist or SDF.
    """
    key = str(module_root)
    if key not in _LOADED:
        try:
            data = json.loads(_cache_path(module_root).read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        # Pure speed cache (§1.1/§5.1): valid JSON of the wrong shape (list/scalar root) is
        # corruption — recompute, never crash. Per-entry shape is checked at the hit site.
        _LOADED[key] = data if isinstance(data, dict) else {}
    return _LOADED[key]


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
    """Dispatched-but-not-reaped runs, restricted to rules the registry still knows.

    A dispatch for an unregistered rule is unreapable — `kernel.py reap --rule` argparse-
    rejects it — so surfacing it would have `decide` return a `REAP` no one can execute,
    every round, forever. An unreapable run is not in flight."""
    dispatched = [
        (e["rule"], e["run"])
        for e in events
        if e["type"] == "dispatch" and e["rule"] in rules.RULES
    ]
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


def live_pins(events: list[dict], oracle_ref: str) -> list[dict]:
    """The pins of oracle_ref with NO later reopen, in event order — so `[-1]` is the
    endorsement currently in force. Set-membership over refs would kill re-pinning forever
    (pin→reopen→pin must yield a live pin again), so liveness is per-pin, not per-ref.

    One implementation, three questions: is the oracle endorsed at all (freshness condition
    3), what grade does it hold (oracle_grade), and what content did the human name
    (signoff_basis). They must not drift apart — a proof's validity and the fingerprint the
    signoff record shows have to be talking about the same pin."""
    return [
        e
        for i, e in enumerate(events)
        if e["type"] == "pin"
        and e["oracle_ref"] == oracle_ref
        and not any(
            r["type"] == "reopen" and r["pin_ref"] == oracle_ref
            for r in events[i + 1 :]
        )
    ]


def oracle_content_fp(module: str, rule) -> str:
    """Current content fingerprint of a proposed oracle, per its Rule.oracle_selector
    (workdir-root-relative glob). Multiple matches merge deterministically (sorted)."""
    root = module_root(module)
    base = root / Path(*rules.workdir_root(rule.name))
    paths = sorted(base.glob(rule.oracle_selector))
    if not paths:
        return UNKNOWN
    if len(paths) == 1 and paths[0].is_file():
        return fingerprint(paths[0])
    h = hashlib.sha256()
    for p in paths:
        h.update(str(p.relative_to(base)).encode() + b"\0")
        h.update(fingerprint(p).encode() + b"\0")
    return "merkle:" + h.hexdigest()


def oracle_grade(module: str, events: list[dict], rule) -> str:
    """LIVE oracle grade (§5.4 ratchet): proposed unless the LATEST live pin's recorded
    content fingerprint matches the oracle's CURRENT content. Derived live over the current
    event log (not a reap-time snapshot in the outcome event) so a pin/reopen takes effect
    immediately — the signoff gate reads this so an endorsement need not wait for a re-reap,
    and a reopen blocks signoff at once."""
    if rule.oracle[1] != "proposed":
        return rule.oracle[1]
    live = live_pins(events, rule.oracle[0])
    if not live:
        return "proposed"
    current = oracle_content_fp(module, rule)
    if current == UNKNOWN:
        return "proposed"  # unreadable oracle content never inherits trust
    # Compare against the LATEST live pin only (spec §5.4 "与最新 pin 记录比对"). `live` is in
    # event order, so live[-1] is the newest; an OLDER live pin matching current content must
    # not resurrect trust the newer endorsement moved on from.
    return "human" if live[-1]["content_fingerprint"] == current else "proposed"


def proof_fresh_except_verdict(
    module: str, events: list[dict], proof_name: str, idx: int, outcome: dict
) -> bool:
    """Conditions 2, 3 and 4 of §1.3 validity — everything except the verdict itself.

    proof_valid adds `verdict == pass`; schedule._fail_is_fresh adds the transitive
    input-closure check. Both ask the same question of these three conditions, so they ask it
    here — and condition 3 is the one that must not be re-derived per caller, because it leans
    two ways: anchored on the outcome instead of the dispatch it is too loose (a bare re-reap
    whitewashes a stale fail, and the scheduler then dispatches upstream rework on a verdict
    whose judge was just reopened); without the live-pin conjunct it is too tight (a re-pinned
    oracle makes a genuinely fresh fail look stale, losing the repair path).
    """
    proof = next((p for p in outcome["proofs"] if p["name"] == proof_name), None)
    if proof is None:
        return False
    root = module_root(module)
    rule = rules.RULES[proof_name]
    # condition 2 (inputs) — every recorded input version must match disk
    for path, recorded in proof.get("inputs", {}).items():
        if not versions_match(recorded, fingerprint_cached(root / path, root)):
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
        if _reopened_after(events, oref, anchor) and not live_pins(events, oref):
            return False
    return True


def proof_valid(module: str, events: list[dict], proof_name: str) -> bool:
    """spec §1.3: a proof is currently valid iff verdict==pass AND every recorded input
    version matches disk AND its oracle ref was not reopened after the proof landed AND
    every recorded output version matches disk (condition 4)."""
    hit = _proof_outcome(events, proof_name)
    if hit is None:
        return False
    idx, outcome = hit
    proof = next(p for p in outcome["proofs"] if p["name"] == proof_name)
    if proof["verdict"] != "pass":
        return False
    return proof_fresh_except_verdict(module, events, proof_name, idx, outcome)


def stale_inputs(module: str, events: list[dict], rule: str) -> list[str]:
    """The recorded inputs of `rule`'s latest outcome whose version no longer matches
    disk — the kernel-computed "what changed since the last run" set a forward re-run
    consumes for scope (it seeds `dispatch.json`'s `scope` at dispatch, see
    kernel.cmd_dispatch). Reuses proof_valid's per-input comparison but COLLECTS the
    mismatches instead of short-circuiting on the first. PIPELINE_INPUTS are excluded
    (mirrors schedule._added_inputs). Empty when the rule never produced an outcome (a first
    delivery) — the caller then falls to full scope. Read-only; stores nothing (NOT the
    retired per-skill classify-delta input_digest — this is a query over the input versions
    already recorded in the log)."""
    hit = _proof_outcome(events, rule)
    if hit is None:
        return []
    _, outcome = hit
    proof = next((p for p in outcome["proofs"] if p["name"] == rule), None)
    if proof is None:
        return []
    root = module_root(module)
    changed: list[str] = []
    for path, recorded in proof.get("inputs", {}).items():
        if path in rules.PIPELINE_INPUTS:
            continue
        if not versions_match(recorded, fingerprint_cached(root / path, root)):
            changed.append(path)
    return changed


def _selector_paths(root: Path, glob: str) -> list[Path]:
    """Resolve a module-relative glob to existing paths (empty match = empty list)."""
    return sorted(root.glob(glob))


def input_available(module: str, events: list[dict], glob: str) -> bool:
    import fnmatch

    if glob in rules.PIPELINE_INPUTS:  # external whitelist — need only exist
        return (module_root(module) / glob).exists()
    prod = rules.producer_of(glob)
    if prod is None:
        return False
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
    if rule.proof is None:
        # No proof ⇒ no freshness contract ⇒ inputs are injected as locations, never gated.
        # A diagnostic (triage) must be dispatchable exactly when upstream proofs are invalid.
        return True
    for globs in rule.inputs.values():
        for g in globs:
            if not input_available(module, events, g):
                return False
    return True


def projection(module: str, events: list[dict]) -> dict[str, str]:
    """Per-stage cell per §4.4: valid | stale | failed | blocked | in-flight | missing.
    Stage cells only — signoff is not a stage and gets no cell; `signed_off` renders it."""
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
    return cells


def signed_off(module: str, events: list[dict]) -> bool:
    """§3.6 判定语: a human landed a `signoff` event AND every stage proof is CURRENTLY
    valid. Both conjuncts are load-bearing — the event carries the human act, and validity
    is re-derived live so that a proof going stale afterwards drops the signoff on its own.

    There is deliberately no unsign verb: `reopen` invalidates its proof via proof_valid
    condition 3, which drops the second conjunct at once. The signoff event is permanent."""
    if not any(e["type"] == "signoff" for e in events):
        return False
    return all(proof_valid(module, events, r) for r in rules.FORWARD_PRIORITY)


def _added_inputs(module: str, rule_name: str, proof: dict) -> list[str]:
    """Files on disk matching rule_name's input selectors but NOT in the proof's recorded
    inputs — i.e. added out-of-band AFTER the proof landed. proof_valid conditions 2/4 only
    check RECORDED paths, so an out-of-band ADD (unlike an edit/delete) escapes them; the
    signoff gate uses this so a smuggled-in source can't ship unverified. Gate-private:
    `signoff_gate` is the sole caller."""
    root = module_root(module)
    recorded = set(proof.get("inputs", {}))
    extra: list[str] = []
    for globs in rules.RULES[rule_name].inputs.values():
        for g in globs:
            if g in rules.PIPELINE_INPUTS:
                continue
            for p in sorted((root).glob(g)):
                rel = str(p.relative_to(root))
                if p.is_file() and rel not in recorded:
                    extra.append(rel)
    return extra


def signoff_gate(module: str, events: list[dict]) -> str | None:
    """Signoff admissibility: EVERY stage proof valid, oracle grade ∈ {tool, human}, no
    out-of-band added input. Returns a one-line reason when the gate fails, else None.
    Callers wrap it in their own vocabulary — `decide` into an ESCALATE action, `kernel
    signoff` into an `ok:false` — because a reason string is neither's dialect to own.

    Iterates FORWARD_PRIORITY in order (never a set): with >1 proof failing the gate, a set
    would make the reason vary with the hash seed, breaching decide's purity invariant."""
    for proof in rules.FORWARD_PRIORITY:
        if not proof_valid(module, events, proof):
            return f"signoff blocked: {proof} not valid"
        _, outcome = _proof_outcome(events, proof)
        p = next(x for x in outcome["proofs"] if x["name"] == proof)
        # Live grade over the current event log — NOT the reap-time snapshot in
        # p["oracle"]["grade"] — so a post-reap pin takes effect at the signoff gate at
        # once (no re-reap) and a reopen blocks signoff immediately.
        if oracle_grade(module, events, rules.RULES[proof]) not in ("tool", "human"):
            return f"signoff blocked: {proof} oracle is proposed (pin it)"
        added = _added_inputs(module, proof, p)
        if added:
            # A new file matching this rule's selectors appeared out-of-band after the
            # proof landed — it was never verified. Only enforced here at the signoff
            # trust boundary (the daily delivery/repair path keeps the cheap recorded-set check).
            return f"signoff blocked: {proof} has unverified new input(s) {added}"
    return None


def signoff_basis(module: str, events: list[dict]) -> list[dict]:
    """What the human is endorsing, per proof — the projection the signoff gate never showed.

    The gate answers "may this be signed"; it says nothing about WHAT. Signoff is where a
    human converts machine self-assessment into signoff-grade trust (ARCHITECTURE §2), and a
    transfer of responsibility only holds if the person can see which proposition they are
    taking on. Every field below is here because it participates in DEFINING that proposition,
    and nothing is here merely because it was recorded:

    - `oracle.grade` is the trust class. `tool` and `human` are different claims about the
      same numbers, and which one this is decides what the signature adds.
    - `oracle.pinned_fingerprint` (human grade only) is WHAT was endorsed. A pin names a
      content fingerprint; without it "an oracle graded human" does not say human-endorsed
      *what*.
    - `tool_versions` — "timing meets" is not a claim about RTL, it is a claim about RTL under
      a given library and tool. Recorded at reap from the environment, so it is the weaker of
      the two homes tool identity has; the version the report itself states lives in that
      stage's own result.json.
    - `inputs` — the proposition is about these bytes. The paths say what the verdict was
      about; their fingerprints are in the log, and the kernel re-checks them on every query,
      so a reviewer does not re-verify by hand. A bare list: a sibling count would only ever
      be its own length.

    Nothing new is computed: this reads the event log the gate already reads. Order follows
    FORWARD_PRIORITY, never a set — a signoff record whose row order varied by hash seed
    would not be a record.
    """
    basis: list[dict] = []
    for proof_name in rules.FORWARD_PRIORITY:
        hit = _proof_outcome(events, proof_name)
        if hit is None:
            continue
        _, outcome = hit
        proof = next((p for p in outcome["proofs"] if p["name"] == proof_name), None)
        if proof is None:
            continue
        rule = rules.RULES[proof_name]
        oracle: dict = {"ref": rule.oracle[0] if rule.oracle else None}
        oracle["grade"] = oracle_grade(module, events, rule) if rule.oracle else None
        if oracle["grade"] == "human":
            live = live_pins(events, rule.oracle[0])
            if live:
                oracle["pinned_fingerprint"] = live[-1]["content_fingerprint"]
        basis.append(
            {
                "proof": proof_name,
                "run": outcome["run"],
                "oracle": oracle,
                "tool_versions": outcome.get("tool_versions", {}),
                "inputs": sorted(proof.get("inputs", {})),
            }
        )
    return basis
