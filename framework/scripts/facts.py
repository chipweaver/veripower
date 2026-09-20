"""Read-only queries over event history and current artifact content."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rules  # noqa: E402

UNKNOWN = "unknown"


def fingerprint(path: Path) -> str:
    """Content version. File -> sha256:<hex>; dir -> merkle:<hex> (sorted walk,
    symlink hashed by its target string, not followed). Missing/unreadable -> UNKNOWN."""
    try:
        if path.is_symlink():
            digest = hashlib.sha256()
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode())
            return "sha256:" + digest.hexdigest()
        if path.is_dir():
            digest = hashlib.sha256()
            entries = []
            for child in sorted(
                path.rglob("*"), key=lambda item: str(item.relative_to(path))
            ):
                relative_path = str(child.relative_to(path))
                if child.is_symlink():
                    entries.append((relative_path, "L", os.readlink(child)))
                elif child.is_file():
                    file_digest = hashlib.sha256()
                    with child.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(65536), b""):
                            file_digest.update(chunk)
                    entries.append((relative_path, "F", file_digest.hexdigest()))
                # directories contribute only via their children's relpaths
            for relative_path, kind, payload in entries:
                digest.update(f"{relative_path}\0{kind}\0{payload}\0".encode())
            return "merkle:" + digest.hexdigest()
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
            return "sha256:" + digest.hexdigest()
    except OSError:
        return UNKNOWN
    return UNKNOWN


def versions_match(recorded: str, current: str) -> bool:
    """True iff both are known and equal. UNKNOWN never matches (conservatively stale)."""
    return recorded == current and recorded != UNKNOWN


def in_flight(events: list[dict]) -> list[dict]:
    """Return dispatched runs without an outcome, restricted to registered rules."""
    dispatched = [
        (event["rule"], event["run"])
        for event in events
        if event["type"] == "dispatch" and event["rule"] in rules.RULES
    ]
    reaped = {
        (event["rule"], event["run"]) for event in events if event["type"] == "outcome"
    }
    return [
        {"rule": stage_name, "run": run_number}
        for (stage_name, run_number) in dispatched
        if (stage_name, run_number) not in reaped
    ]


def latest_outcome(events: list[dict], rule: str) -> dict | None:
    for event in reversed(events):
        if event["type"] == "outcome" and event["rule"] == rule:
            return event
    return None


def run_workdir(events, rule, run):
    """Return the workdir recorded for a rule's run, or None if it was not dispatched."""
    for event in events:
        if (
            event["type"] == "dispatch"
            and event["rule"] == rule
            and event["run"] == run
        ):
            return event["workdir"]
    return None


def declared_fix_owner(module: str, rule: str) -> str | None:
    """Read fix_owner from the failed rule's canonical result.

    Return a registered rule name, or None when no owner can be read."""
    result_path = Path(module) / Path(*rules.RULES[rule].workdir_root) / "result.json"
    try:
        stage_specific = json.loads(result_path.read_text()).get("stage_specific", {})
    except (OSError, ValueError):
        return None
    owner = stage_specific.get("fix_owner")
    return owner if owner in rules.RULES else None


# Freshness: proof validity, input availability, projection


def proof_outcome(events: list[dict], proof_name: str) -> tuple[int, dict] | None:
    """Read this stage's latest outcome; an incomplete result has no current proof."""
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if event["type"] == "outcome" and event["rule"] == proof_name:
            return (
                (index, event)
                if any(proof["name"] == proof_name for proof in event["proofs"])
                else None
            )
    return None


def proof_valid(module: str, events: list[dict], proof_name: str) -> bool:
    """A passing conclusion remains valid while its recorded inputs and outputs match."""
    hit = proof_outcome(events, proof_name)
    if hit is None:
        return False
    unused, outcome = hit
    proof = next(proof for proof in outcome["proofs"] if proof["name"] == proof_name)
    if proof["verdict"] != "pass":
        return False
    root = Path(module)
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
    unused, outcome = hit
    proof = next(proof for proof in outcome["proofs"] if proof["name"] == rule)
    root = Path(module)
    changed: list[str] = []
    for path, recorded in proof.get("inputs", {}).items():
        if path in rules.PIPELINE_INPUTS:
            continue
        if not versions_match(recorded, fingerprint(root / path)):
            changed.append(path)
    return changed


def input_available(module: str, events: list[dict], glob: str) -> bool:
    import fnmatch

    if glob in rules.PIPELINE_INPUTS:
        # External inputs require the intent entry document.
        return (Path(module) / rules.INTENT_DOC).exists()
    producer = rules.producer_of(glob)
    if producer is None:
        return False
    outcome = latest_outcome(events, producer)
    if outcome is None:
        # A producer must have recorded its outputs.
        return False
    root = Path(module)
    matched = False
    for path, recorded in outcome.get("outputs", {}).items():
        if fnmatch.fnmatch(path, glob):
            matched = True
            if not versions_match(recorded, fingerprint(root / path)):
                return False
    if not matched and not any(root.glob(glob)):
        # Require a recorded match or an existing selected path.
        return False
    producer_rule = rules.RULES[producer]
    if producer_rule.proof:
        return proof_valid(module, events, producer_rule.proof)
    return True


def rule_available(module: str, events: list[dict], rule_name: str) -> bool:
    rule = rules.RULES[rule_name]
    if rule.proof is None:
        # No proof ⇒ no freshness contract ⇒ inputs are injected as locations, never gated.
        # A diagnostic (triage) must be dispatchable exactly when upstream proofs are invalid.
        return True
    for globs in rule.inputs.values():
        for selector in globs:
            if not input_available(module, events, selector):
                return False
    return True


def projection(module: str, events: list[dict]) -> dict[str, str]:
    """Per-stage cell: valid | stale | failed | blocked | in-flight | missing.
    Stage cells only — signoff is not a stage and gets no cell; `signed_off` renders it."""
    flying = {execution["rule"] for execution in in_flight(events)}
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


def unrecorded_artifacts(module: str, rule_name: str, outcome: dict) -> list[str]:
    """Find canonical files not covered by the latest outcome, excluding run history."""
    root = Path(module)
    stage = root / Path(*rules.RULES[rule_name].workdir_root)
    if not stage.is_dir():
        return []
    covered: set[Path] = set()
    for relative_path in outcome.get("outputs", {}):
        artifact_path = root / relative_path
        if artifact_path.is_dir():
            covered |= {
                file_path
                for file_path in artifact_path.rglob("*")
                if file_path.is_file()
            }
        else:
            covered.add(artifact_path)
    return sorted(
        str(file_path.relative_to(root))
        for file_path in stage.rglob("*")
        if file_path.is_file()
        and file_path.relative_to(stage).parts[0]
        != "runs"  # the run history, not a delivered product
        and file_path not in covered
    )


def signoff_gate(module: str, events: list[dict]) -> str | None:
    """Return the first unmet signoff requirement in forward priority order.

    Require valid proofs and no unrecorded products."""
    for proof in rules.FORWARD_PRIORITY:
        if not proof_valid(module, events, proof):
            return f"signoff blocked: {proof} not valid"
        unused, outcome = proof_outcome(events, proof)
        added = unrecorded_artifacts(module, proof, outcome)
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
        unused, outcome = hit
        proof = next(
            proof for proof in outcome["proofs"] if proof["name"] == proof_name
        )
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
