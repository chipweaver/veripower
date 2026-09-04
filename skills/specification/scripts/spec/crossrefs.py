#!/usr/bin/env python3
"""check-crossrefs — the one check the specification stage's fan-out makes necessary.

Wave 1 authors the ledger and the sidecars; N wave-2 children each author their own doc and check
hints, in parallel, none able to see another's context. So two things can be wrong that no single
author is in a position to notice: a name one file writes that the owning file does not have, and
a requirement nothing anywhere verifies. Both are set operations over identifiers that exist for a
downstream consumer anyway, so the whole verb is a join. It runs after the last wave-2 author
finishes, because that is when the question first has an answer.

Each violation names both sides in words — which file wrote the name, and which file was
supposed to have it. WHICH side is wrong is a judgment (the child may have mistyped the port, or
the boundary may be missing it), so the verdict states the disagreement and leaves that call to
whoever reads the two files.

Deliberately NOT here: a sidecar's own shape (validated by whoever reads it — see sidecar.py),
the top-partition purity rule (decided at the partition gate — see ports.py), and anything
needing a reference frame, such as whether a doc realizes a requirement. Those are a reader's job.

Usage: ``python3 scripts/spec/__main__.py check-crossrefs --workdir {workdir}``
Exit: 0 if `status == "pass"`, 1 if `status == "fail"`.
"""

import json
import re
from pathlib import Path

import yaml

from spec import ledger
from spec.sidecar import read_sidecar

# Every child .md must declare these frontmatter keys (presence check; empty value is OK) —
# an absent key would make its subset check below vacuously true.
_REQUIRED_FM_KEYS = ("ports", "clocks")


def parse_frontmatter(sub_text: str) -> dict:
    """Parse the YAML front-matter block (``--- ... ---``) at the top of a child doc;
    returns ``{}`` when there is no front-matter block."""
    m = re.match(r"^---\n(.*?)\n---\n", sub_text, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def _names(entries, *keys) -> set[str]:
    return {e[k] for e in entries for k in keys if isinstance(e.get(k), str) and e[k]}


def violations(workdir: Path, manifest: dict, child_texts: dict) -> list[dict]:
    """Every cross-file disagreement in the workdir, each stated as where + what."""
    ports = read_sidecar(workdir, "top-io.json")
    wires = read_sidecar(workdir, "interconnects.json")
    clock_names = _names(read_sidecar(workdir, "clocks.json"), "name")
    rows = ledger.load(workdir)
    row_ids = {r["id"] for r in rows}
    hintable = ledger.hintable_ids(rows)
    port_names = _names(ports, "name") | _names(wires, "wire")

    out: list[dict] = []

    def say(where, what):
        out.append({"where": where, "what": what})

    # A child's frontmatter is its claim about which of the shared boundary is its own. The
    # sidecars are Wave 1's claim about what the boundary is. Two authors, two facts.
    named: set[str] = set()
    claimed: set[str] = set()
    check_ids: dict[str, str] = {}
    for child in manifest["children"]:
        cname = child["name"]
        doc = child["doc"]
        fm = parse_frontmatter(child_texts[cname])
        for key in _REQUIRED_FM_KEYS:
            if key not in fm:
                say(
                    f"{doc} frontmatter",
                    f"no {key!r} key — an absent key is not an empty one, and would make "
                    f"its check pass vacuously",
                )
        for p in fm.get("ports") or []:
            if p not in port_names:
                say(
                    f"{doc} frontmatter ports",
                    f"{p!r} is in neither top-io.json nor interconnects.json",
                )
        for c in fm.get("clocks") or []:
            cn = c.get("name") if isinstance(c, dict) else c
            if cn and cn not in clock_names:
                say(f"{doc} frontmatter clocks", f"{cn!r} is not in clocks.json")
        claimed |= set(fm.get("ports") or [])

        # A hint says how simulation observes a requirement. It may name only rows simulation
        # judges without a coverage target: any other row is established elsewhere, and a hint
        # for it would turn a requirement the engineer kept out of the testbench into a gate.
        hints_file = f"check-hints/{cname}.json"
        for h in read_sidecar(workdir, hints_file, schema="check-hints.schema.json"):
            cid = h["check_id"]
            if cid in check_ids:
                say(f"{hints_file} {cid}", f"check_id already used in {check_ids[cid]}")
            check_ids.setdefault(cid, hints_file)
            for rid in h["requirements"]:
                if rid not in row_ids:
                    say(
                        f"{hints_file} {cid}",
                        f"names {rid!r}, which requirements.json does not have",
                    )
                elif rid not in hintable:
                    say(
                        f"{hints_file} {cid}",
                        f"names {rid!r}, which is not a simulation row without a target; "
                        f"only those take hints",
                    )
                named.add(rid)

    # A phantom clock domain would render `abstract_port -clock <phantom>` and hide a CDC path.
    for e in ports:
        if e.get("clock_domain") and e["clock_domain"] not in clock_names:
            say(
                f"top-io.json {e.get('name')}",
                f"clock_domain {e['clock_domain']!r} is not in clocks.json",
            )
    for w in wires:
        if w.get("clock_domain") and w["clock_domain"] not in clock_names:
            say(
                f"interconnects.json {w.get('wire')}",
                f"clock_domain {w['clock_domain']!r} is not in clocks.json",
            )

    # Orphans. The naming side is authored decentrally by the N children, so no one author
    # can see that a requirement went unclaimed.
    for rid in sorted(hintable - named):
        say(
            f"requirements.json {rid}",
            "no check-hints entry names it, so nothing verifies it",
        )
    # WHICH child drives an output, when several claim it, is not asked: a top mux of N leaf
    # sources and N leaves conflicting are indistinguishable from the claims alone.
    for e in ports:
        if e.get("direction") == "output" and e.get("name") not in claimed:
            say(
                f"top-io.json {e.get('name')}",
                "no child lists it in frontmatter ports, so nothing drives it",
            )
    return out


def verdict(workdir) -> dict:
    """The verdict as data (no printing, no exit). finalize re-runs this in-process as the
    divergence-proof invariant: every check is a join over the workdir's own files, so a clean
    gate verdict stays true unless an artifact was edited after the gate."""
    workdir_p = Path(workdir)
    manifest = json.loads((workdir_p / "manifest.json").read_text(encoding="utf-8"))
    child_texts = {
        child["name"]: (workdir_p / child["doc"]).read_text(encoding="utf-8")
        for child in manifest["children"]
    }
    found = violations(workdir_p, manifest, child_texts)
    return {"status": "fail" if found else "pass", "violations": found}


def run(workdir: str) -> int:
    v = verdict(workdir)
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0 if v["status"] == "pass" else 1
