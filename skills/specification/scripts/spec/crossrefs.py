#!/usr/bin/env python3
"""Validate declared references between requirements, boundary and check hints.

Errors identify inconsistent or missing inputs. The stage owner determines which input
is wrong from the task evidence; a nonzero exit does not determine the repair owner.
Finalize repeats this check on the artifacts being delivered. Structural consistency
alone does not establish that a requirement or observation is correct.
"""

from pathlib import Path

from spec.sidecar import read_sidecar


def violations(workdir: Path) -> list[dict]:
    """Every cross-file disagreement in the workdir, each stated as where + what."""
    ports = read_sidecar(workdir, "top-io.json")
    clock_names = {
        c["name"] for c in read_sidecar(workdir, "clocks.json") if c.get("name")
    }
    rows = read_sidecar(workdir, "requirements.json")
    row_ids = {r["id"] for r in rows}
    hintable = {
        row["id"]
        for row in rows
        if row["judge"] == "simulation" and "target" not in row
    }

    out: list[dict] = []

    def _record_violation(where, what):
        out.append({"where": where, "what": what})

    # Validate the declared simulation-check references. If an assignment omits required
    # behavior, the author must correct it against the task rather than drop the check.
    named: set[str] = set()
    check_ids: set[str] = set()
    for h in read_sidecar(workdir, "check-hints.json"):
        cid = h["check_id"]
        if cid in check_ids:
            _record_violation(
                f"check-hints.json {cid}", "check_id already used in this file"
            )
        check_ids.add(cid)
        for rid in h["requirements"]:
            if rid not in row_ids:
                _record_violation(
                    f"check-hints.json {cid}",
                    f"names {rid!r}, which requirements.json does not have",
                )
            elif rid not in hintable:
                _record_violation(
                    f"check-hints.json {cid}",
                    f"names {rid!r}, which is not a simulation row without a target; "
                    f"only those take hints",
                )
            named.add(rid)

    # Orphans. Nothing else asks whether every row simulation judges has an observation.
    for rid in sorted(hintable - named):
        _record_violation(
            f"requirements.json {rid}",
            "no check-hints entry names it, so nothing verifies it",
        )

    # A phantom clock domain would render `abstract_port -clock <phantom>` and hide a CDC path.
    for e in ports:
        if e.get("clock_domain") and e["clock_domain"] not in clock_names:
            _record_violation(
                f"top-io.json {e.get('name')}",
                f"clock_domain {e['clock_domain']!r} is not in clocks.json",
            )
    return out


def verdict(workdir) -> dict:
    """The verdict as data (no printing, no exit). finalize re-runs this in-process as the
    divergence-proof invariant: every check is a join over the workdir's own files, so a clean
    gate verdict stays true unless an artifact was edited after the gate."""
    found = violations(Path(workdir))
    return {"status": "fail" if found else "pass", "violations": found}
