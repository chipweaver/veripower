"""Read-only queries over event history and current artifact content."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rules  # noqa: E402
import store  # noqa: E402

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


def runs_of(events: list[dict], rule: str) -> int:
    return sum(1 for e in events if e["type"] == "dispatch" and e["rule"] == rule)


def in_flight(events: list[dict]) -> list[dict]:
    """Return dispatched runs without an outcome, restricted to registered rules."""
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


def run_workdir(events, rule, run):
    """Return the workdir recorded for a rule's run, or None if it was not dispatched."""
    for e in events:
        if e["type"] == "dispatch" and e["rule"] == rule and e["run"] == run:
            return e["workdir"]
    return None


def declared_fix_owner(module: str, rule: str) -> str | None:
    """Read fix_owner from the failed rule's canonical result.

    Return a registered rule name, or None when no owner can be read."""
    p = store.module_root(module) / Path(*rules.workdir_root(rule)) / "result.json"
    try:
        ss = json.loads(p.read_text()).get("stage_specific", {})
    except (OSError, ValueError):
        return None
    owner = ss.get("fix_owner")
    return owner if owner in rules.RULES else None


# Freshness: proof validity, input availability, projection


def proof_outcome(events: list[dict], proof_name: str) -> tuple[int, dict] | None:
    """Read this stage's latest outcome; an incomplete result has no current proof."""
    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        if e["type"] == "outcome" and e["rule"] == proof_name:
            return (i, e) if any(p["name"] == proof_name for p in e["proofs"]) else None
    return None


def proof_valid(module: str, events: list[dict], proof_name: str) -> bool:
    """A passing conclusion remains valid while its recorded inputs and outputs match."""
    hit = proof_outcome(events, proof_name)
    if hit is None:
        return False
    _, outcome = hit
    proof = next(p for p in outcome["proofs"] if p["name"] == proof_name)
    if proof["verdict"] != "pass":
        return False
    root = store.module_root(module)
    return all(
        versions_match(recorded, fingerprint(root / path))
        for table in (proof["inputs"], outcome["outputs"])
        for path, recorded in table.items()
    )


def stale_inputs(module: str, events: list[dict], rule: str) -> list[str]:
    """Return recorded producer inputs whose content has changed since the latest outcome.

    The external intent tree is excluded from edit scope, while still participating
    in proof validity. A first delivery has no recorded scope."""
    hit = proof_outcome(events, rule)
    if hit is None:
        return []
    _, outcome = hit
    proof = next((p for p in outcome["proofs"] if p["name"] == rule), None)
    if proof is None:
        return []
    root = store.module_root(module)
    changed: list[str] = []
    for path, recorded in proof.get("inputs", {}).items():
        if path in rules.PIPELINE_INPUTS:
            continue
        if not versions_match(recorded, fingerprint(root / path)):
            changed.append(path)
    return changed


def _selector_paths(root: Path, glob: str) -> list[Path]:
    """Resolve a module-relative glob to existing paths (empty match = empty list)."""
    return sorted(root.glob(glob))


def input_available(module: str, events: list[dict], glob: str) -> bool:
    import fnmatch

    if glob in rules.PIPELINE_INPUTS:
        # External inputs require the intent entry document.
        return (store.module_root(module) / rules.INTENT_DOC).exists()
    prod = rules.producer_of(glob)
    if prod is None:
        return False
    outcome = latest_outcome(events, prod)
    if outcome is None:
        # A producer must have recorded its outputs.
        return False
    root = store.module_root(module)
    matched = False
    for path, recorded in outcome.get("outputs", {}).items():
        if fnmatch.fnmatch(path, glob):
            matched = True
            if not versions_match(recorded, fingerprint(root / path)):
                return False
    if not matched and not _selector_paths(root, glob):
        # Require a recorded match or an existing selected path.
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
    """Per-stage cell: valid | stale | failed | blocked | in-flight | missing.
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
    """The current evidence must still be the evidence accepted at the last signoff."""
    anchor = next(
        (i for i in range(len(events) - 1, -1, -1) if events[i]["type"] == "signoff"),
        None,
    )
    if anchor is None or signoff_gate(module, events) is not None:
        return False
    accepted = events[:anchor]
    for name in rules.FORWARD_PRIORITY:
        before = proof_outcome(accepted, name)
        current = proof_outcome(events, name)
        if before is None or current is None:
            return False
        evidence = [
            {key: value for key, value in hit[1].items() if key != "ts"}
            for hit in (before, current)
        ]
        if evidence[0] != evidence[1]:
            return False
    return True


def _unrecorded(module: str, rule_name: str, outcome: dict) -> list[str]:
    """Find canonical files not covered by the latest outcome, excluding run history."""
    root = store.module_root(module)
    stage = root / Path(*rules.RULES[rule_name].workdir_root)
    if not stage.is_dir():
        return []
    covered: set[Path] = set()
    for rel in outcome.get("outputs", {}):
        p = root / rel
        if p.is_dir():
            covered |= {q for q in p.rglob("*") if q.is_file()}
        else:
            covered.add(p)
    return sorted(
        str(q.relative_to(root))
        for q in stage.rglob("*")
        if q.is_file()
        and q.relative_to(stage).parts[0]
        != "runs"  # the run history, not a delivered product
        and q not in covered
    )


def signoff_gate(module: str, events: list[dict]) -> str | None:
    """Return the first unmet signoff requirement in forward priority order.

    Require valid proofs and no unrecorded products."""
    for proof in rules.FORWARD_PRIORITY:
        if not proof_valid(module, events, proof):
            return f"signoff blocked: {proof} not valid"
        _, outcome = proof_outcome(events, proof)
        added = _unrecorded(module, proof, outcome)
        if added:
            # Signoff also checks for unrecorded products.
            return f"signoff blocked: {proof} has unrecorded file(s) {added}"
    return None


def signoff_basis(events: list[dict]) -> list[dict]:
    """Assemble the proposition being signed, in forward priority order.

    Include each proof's run, tool identity, requirement verdicts and input paths."""
    basis: list[dict] = []
    for proof_name in rules.FORWARD_PRIORITY:
        hit = proof_outcome(events, proof_name)
        if hit is None:
            continue
        _, outcome = hit
        proof = next((p for p in outcome["proofs"] if p["name"] == proof_name), None)
        if proof is None:
            continue
        basis.append(
            {
                "proof": proof_name,
                "run": outcome["run"],
                "tool_versions": outcome.get("tool_versions", {}),
                "requirements": outcome.get("requirements", []),
                "inputs": sorted(proof.get("inputs", {})),
            }
        )
    return basis
