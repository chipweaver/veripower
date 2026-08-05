#!/usr/bin/env python3
"""Why did decide say that, at decision point k? Rebuild the tree and dump the predicates."""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import replay as R  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--scripts", required=True)
ap.add_argument("-k", type=int, required=True)
a = ap.parse_args()

sys.path.insert(0, str(Path(a.scripts).resolve()))
import facts  # noqa: E402
import rules  # noqa: E402
import schedule  # noqa: E402

events = [json.loads(ln) for ln in R.LOG.read_text().splitlines() if ln.strip()]
events, _ = R.augment(events, rules)
sur = R.Surrogate(events, facts)
bfp = None
for e in events:
    for src in [e.get("inputs") or {}] + [
        p.get("inputs") or {} for p in (e.get("proofs") or [])
    ]:
        if "brainstorm.md" in src:
            bfp = src["brainstorm.md"]
    if bfp:
        break

e = events[a.k]
prefix = events[: a.k]
ready = None
if e["type"] == "outcome":
    ready = next(
        (
            d.get("workdir")
            for d in prefix
            if d["type"] == "dispatch"
            and d["rule"] == e["rule"]
            and d["run"] == e["run"]
        ),
        None,
    )
tree = R.SCRATCH / "tree-probe" / "m"
R.materialize(tree, prefix, sur, bfp, ready)
m = str(tree)
ev = facts.read_events(m)

print(f"k={a.k}  real next = {e['type']} {e.get('rule')}:{e.get('run')}")
print("decide ->", json.dumps(schedule.decide(m), ensure_ascii=False)[:300])
print()
print(
    f"{'rule':18s} {'proof_valid':12s} {'rule_available':15s} stale_inputs / missing input selectors"
)
for name in rules.FORWARD_PRIORITY:
    pv = facts.proof_valid(m, ev, name) if rules.RULES[name].proof else "-"
    ra = facts.rule_available(m, ev, name)
    miss = []
    for key, globs in rules.RULES[name].inputs.items():
        for g in globs:
            if rules.producer_of(g) == name:
                continue
            if not list(Path(m).glob(g)):
                miss.append(g)
    st = facts.stale_inputs(m, ev, name)
    print(
        f"{name:18s} {str(pv):12s} {str(ra):15s} stale={st[:3]}{'...' if len(st) > 3 else ''} missing={miss}"
    )
