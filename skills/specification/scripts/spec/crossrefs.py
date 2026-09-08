#!/usr/bin/env python3
"""check-crossrefs — the joins no single author of this stage's artifacts can see.

The ledger, the boundary and the check hints are authored by different sub-Tasks. So two things
can be wrong that no one author is in a position to notice: a hint naming a row that is not the
ledger's to hint, and a row simulation judges that nothing anywhere verifies. Both are set
operations over identifiers that exist for a downstream consumer anyway, so the whole verb is a
join.

Each violation names both sides in words — which file wrote the name, and which file was
supposed to have it. WHICH side is wrong is a judgment, so the verdict states the disagreement
and leaves that call to whoever reads the two files.

Deliberately NOT here: a sidecar's own shape (validated by whoever reads it — see sidecar.py),
and anything needing a reference frame, such as whether a document realizes a requirement. Those
are a reader's job.

Usage: ``python3 scripts/spec/__main__.py check-crossrefs --workdir {workdir}``
Exit: 0 if `status == "pass"`, 1 if `status == "fail"`. A missing or malformed sidecar is also 1,
via the CLI's uniform SidecarError handler: it is routable — re-dispatch whoever authors that file
— which is what exit 1 means. Nothing here can fail any other way, since every read goes through
`read_sidecar`.
"""

import json
from pathlib import Path

from spec import ledger
from spec.sidecar import read_sidecar


def violations(workdir: Path) -> list[dict]:
    """Every cross-file disagreement in the workdir, each stated as where + what."""
    ports = read_sidecar(workdir, "top-io.json")
    clock_names = {
        c["name"] for c in read_sidecar(workdir, "clocks.json") if c.get("name")
    }
    rows = ledger.load(workdir)
    row_ids = {r["id"] for r in rows}
    hintable = ledger.hintable_ids(rows)

    out: list[dict] = []

    def say(where, what):
        out.append({"where": where, "what": what})

    # A hint says how simulation observes a requirement. It may name only rows simulation judges
    # without a coverage target: any other row is established elsewhere, and a hint for it would
    # turn a requirement the engineer kept out of the testbench into a gate.
    named: set[str] = set()
    check_ids: set[str] = set()
    for h in read_sidecar(workdir, "check-hints.json"):
        cid = h["check_id"]
        if cid in check_ids:
            say(f"check-hints.json {cid}", "check_id already used in this file")
        check_ids.add(cid)
        for rid in h["requirements"]:
            if rid not in row_ids:
                say(
                    f"check-hints.json {cid}",
                    f"names {rid!r}, which requirements.json does not have",
                )
            elif rid not in hintable:
                say(
                    f"check-hints.json {cid}",
                    f"names {rid!r}, which is not a simulation row without a target; "
                    f"only those take hints",
                )
            named.add(rid)

    # Orphans. Nothing else asks whether every row simulation judges has an observation.
    for rid in sorted(hintable - named):
        say(
            f"requirements.json {rid}",
            "no check-hints entry names it, so nothing verifies it",
        )

    # A phantom clock domain would render `abstract_port -clock <phantom>` and hide a CDC path.
    for e in ports:
        if e.get("clock_domain") and e["clock_domain"] not in clock_names:
            say(
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


def run(workdir: str) -> int:
    v = verdict(workdir)
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0 if v["status"] == "pass" else 1
