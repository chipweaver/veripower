#!/usr/bin/env python3
"""check-crossrefs — the one check the specification stage's fan-out makes necessary.

Wave 1 authors the sidecars; N wave-2 children each author their own doc and check hints, in
parallel, none able to see another's context. Two things can then be wrong that **no single
author is in a position to notice**:

  * a name one file writes does not exist in the file that owns it (`unresolved`);
  * something nothing anywhere refers to (`orphans`) — a feature no check hint names, a top
    output no child claims to drive.

Both are set operations over identifiers that exist for a downstream consumer anyway, so the
whole verb is a join. It runs after the last wave-2 author finishes, because that is when the
question first has an answer.

Deliberately NOT here: a sidecar's own shape (validated by whoever reads it — see sidecar.py),
the top-partition purity rule (decided at the partition gate — see ports.py), and anything
needing a reference frame, such as whether the doc realizes the brainstorm or whether an
encoding is adequate. Those are a reader's job.

Usage: ``python3 scripts/spec/__main__.py check-crossrefs --workdir {workdir}``
Exit: 0 if `status == "pass"`, 1 if `status == "fail"`.
"""

import json
import re
from pathlib import Path

import yaml

from spec.sidecar import read_sidecar

# Every child .md must declare these frontmatter keys (presence check; empty value is OK) —
# an absent key would make its subset check below vacuously true.
_REQUIRED_FM_KEYS = ("ports", "clocks", "features")


def parse_frontmatter(sub_text: str) -> dict:
    """Parse the YAML front-matter block (``--- ... ---``) at the top of a child doc;
    returns ``{}`` when there is no front-matter block."""
    m = re.match(r"^---\n(.*?)\n---\n", sub_text, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def _names(entries, *keys) -> set[str]:
    return {e[k] for e in entries for k in keys if isinstance(e.get(k), str) and e[k]}


def compute_unresolved(workdir: Path, manifest: dict, child_texts: dict) -> dict:
    """Every name written in one file resolves against the file that owns it.

    The child-frontmatter half is not a same-fact-twice check: the sidecars are Wave 1's claim
    about the boundary, the frontmatter is the child author's claim about which of it is
    theirs. Two authors, two facts — a cross-reference that does not resolve is a real defect.
    """
    ports = read_sidecar(workdir, "top-io.json")
    wires = read_sidecar(workdir, "interconnects.json")
    clock_names = _names(read_sidecar(workdir, "clocks.json"), "name")
    feature_ids = _names(read_sidecar(workdir, "features.json"), "id")
    port_names = _names(ports, "name") | _names(wires, "wire")

    child_ports: list[dict] = []
    child_clocks: list[dict] = []
    child_features: list[dict] = []
    missing_keys: list[dict] = []
    for child in manifest["children"]:
        cname = child["name"]
        fm = parse_frontmatter(child_texts[cname])
        missing = [k for k in _REQUIRED_FM_KEYS if k not in fm]
        if missing:
            missing_keys.append({"child": cname, "missing": missing})
        for p in fm.get("ports") or []:
            if p not in port_names:
                child_ports.append({"child": cname, "port": p})
        for c in fm.get("clocks") or []:
            cn = c.get("name") if isinstance(c, dict) else c
            if cn and cn not in clock_names:
                child_clocks.append({"child": cname, "clock_name": cn})
        for f in fm.get("features") or []:
            if f not in feature_ids:
                child_features.append({"child": cname, "feature_id": f})

    # clock_domain ⊆ clocks.json names, on both boundary sidecars: a phantom domain would
    # render `abstract_port -clock <phantom>` and hide a CDC path.
    port_domains = [
        {"signal": e.get("name"), "clock_domain": e["clock_domain"]}
        for e in ports
        if e.get("clock_domain") and e["clock_domain"] not in clock_names
    ]
    wire_domains = [
        {"wire": w.get("wire"), "clock_domain": w["clock_domain"]}
        for w in wires
        if w.get("clock_domain") and w["clock_domain"] not in clock_names
    ]
    return {
        "child_ports": child_ports,
        "child_clocks": child_clocks,
        "child_features": child_features,
        "missing_frontmatter_keys": missing_keys,
        "port_clock_domains": port_domains,
        "wire_clock_domains": wire_domains,
    }


def compute_orphans(workdir: Path, manifest: dict, child_texts: dict) -> dict:
    """Things nothing refers to. Both halves are emergent: the referring side is authored
    decentrally by the N children, so no one author can see that a target went unclaimed."""
    feature_ids = _names(read_sidecar(workdir, "features.json"), "id")
    referenced: set[str] = set()
    claimed: set[str] = set()
    for cname, body in child_texts.items():
        hints = read_sidecar(
            workdir, f"check-hints/{cname}.json", schema="check-hints.schema.json"
        )
        referenced |= _names(hints, "source_feature")
        claimed |= set(parse_frontmatter(body).get("ports") or [])

    # WHICH child drives an output, when several claim it, is not asked: a top mux of N leaf
    # sources and N leaves conflicting are indistinguishable from the claims alone, and only a
    # reader of the bodies can tell them apart.
    outputs = [
        {"signal": e["name"]}
        for e in read_sidecar(workdir, "top-io.json")
        if e.get("direction") == "output"
        and isinstance(e.get("name"), str)
        and e["name"] not in claimed
    ]
    return {
        "features_without_check": [
            {"feature_id": fid} for fid in sorted(feature_ids - referenced)
        ],
        "outputs_without_driver": outputs,
    }


def verdict(workdir) -> dict:
    """The verdict as data (no printing, no exit). finalize re-runs this in-process as the
    divergence-proof invariant: every check is a join over the workdir's own files, so a clean
    Step-5 verdict stays true unless an artifact was edited after the gate."""
    workdir_p = Path(workdir)
    manifest = json.loads((workdir_p / "manifest.json").read_text(encoding="utf-8"))
    child_texts = {
        child["name"]: (workdir_p / child["doc"]).read_text(encoding="utf-8")
        for child in manifest["children"]
    }
    unresolved = compute_unresolved(workdir_p, manifest, child_texts)
    orphans = compute_orphans(workdir_p, manifest, child_texts)
    return {
        "status": "fail"
        if any(unresolved.values()) or any(orphans.values())
        else "pass",
        "unresolved": unresolved,
        "orphans": orphans,
    }


def violated_keys(v: dict) -> list[str]:
    """The non-empty violation lists in a verdict — what a caller reports when it has no room
    for the whole document."""
    return [k for block in ("unresolved", "orphans") for k, x in v[block].items() if x]


def run(workdir: str) -> int:
    v = verdict(workdir)
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0 if v["status"] == "pass" else 1
