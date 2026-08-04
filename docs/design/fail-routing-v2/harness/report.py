#!/usr/bin/env python3
"""Read a grid jsonl and produce the readable tables + the anomaly lists.

Anomalies are stated as PROPERTIES the scheduler should have, each checked over every
scenario that can express it. A property is not "the current code does X" — it is what a
reader of ARCHITECTURE.md would predict — so a hit is either a real defect or a documented
trade-off, and the report says which by naming the property.

    python3 report.py [--tag baseline] [--anomaly A1] [--show 10]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import space  # noqa: E402

OUT = Path(__file__).parent.parent / "out"


def load(tag):
    return [json.loads(x) for x in (OUT / f"grid-{tag}.jsonl").open()]


def opened(rec):
    """Rules the scheduler opened (dispatched) before the turn settled."""
    return [a["rule"] for a in rec["raw"] if a["action"] == "DISPATCH"]


def routed(rec):
    """(rule, caused_by) of each DISPATCH that answers at least one failure."""
    return [
        (a["rule"], [tuple(c) for c in a.get("caused_by", [])])
        for a in rec["raw"]
        if a["action"] == "DISPATCH" and a.get("caused_by")
    ]


def startable_owners(rec):
    """Owners this state could actually have dispatched: inputs available, and not one of
    the two rules that is itself failing (a rule whose own failure is unattributed answers
    nothing by running). Properties about DELIVERY apply only to these — a state where the
    owner cannot legally start is not a state where anything was dropped."""
    failing = {rec.get("a"), rec.get("b")}
    return {
        o
        for o in expected_owners(rec)
        if o in rec.get("available", []) and o not in failing
    }


def expected_owners(rec):
    if rec["kind"] == "single-fail":
        o = space.owner_of(rec["a"], rec["cat_a"])
        return {o} if o else set()
    if rec["kind"] == "both-fail":
        return {
            o
            for o in (
                space.owner_of(rec["a"], rec["cat_a"]),
                space.owner_of(rec["b"], rec["cat_b"]),
            )
            if o
        }
    return set()


# ── properties ────────────────────────────────────────────────────────────────────

PROPS = {}


def prop(key, statement):
    def deco(fn):
        PROPS[key] = (statement, fn)
        return fn

    return deco


@prop("A1", "no two runs open at once are related by the input closure")
def a1(rec):
    op = opened(rec)
    for i, x in enumerate(op):
        for y in op[i + 1 :]:
            if space.relation(x, y) in ("upstream", "downstream"):
                return f"{x} + {y} ({space.relation(x, y)})"
    # a rule opened under one already in flight counts too (the `inflight` scenarios)
    if rec["kind"] == "inflight":
        for y in op:
            if space.relation(rec["running"], y) in ("upstream", "downstream"):
                return f"{rec['running']}(in flight) + {y}"
    return None


@prop("A2", "every failure carrying a legal owner is answered by some dispatch")
def a2(rec):
    exp = startable_owners(rec)
    if not exp:
        return None
    answered = {r for r, _ in routed(rec)}
    missing = exp - answered
    return ",".join(sorted(missing)) if missing else None


@prop("A3", "two failures naming the SAME owner are merged into one dispatch")
def a3(rec):
    if rec["kind"] != "both-fail" or rec.get("owner_rel") != "same-owner":
        return None
    for _, cb in routed(rec):
        if len(cb) >= 2:
            return None
    return "caused_by names one failure"


@prop("A4", "an unroutable failure never blocks a routable one")
def a4(rec):
    if not startable_owners(rec):
        return None
    if rec["raw"] and rec["raw"][0]["action"] == "ESCALATE":
        return rec["raw"][0]["reason"]
    return None


@prop("A5", "a reliable diagnosis is cited by the dispatch it caused")
def a5(rec):
    want = set()
    startable = startable_owners(rec)
    for side in ("a", "b"):
        r, c = rec.get(side), rec.get(f"cat_{side}")
        if r and c and c.startswith("diag:") and space.owner_of(r, c) in startable:
            want.add(f"d-{r}-2")
    if not want:
        return None
    cited = {x for a in rec["raw"] for x in a.get("diagnosis_refs", [])}
    missing = want - cited
    return ",".join(sorted(missing)) if missing else None


@prop("A0", "a legal conclusion is DELIVERED: the failing run's own envelope reaches its "
      "owner's dispatch.json")
def a0(rec):
    """Delivery, not dispatch. A round can be sent to the right owner and told nothing —
    that is what a cascade rebuild does, and the stage then cannot judge what it must fix."""
    want = set()
    startable = startable_owners(rec)
    for side in ("a", "b"):
        r, c = rec.get(side), rec.get(f"cat_{side}")
        if r and c and space.owner_of(r, c) in startable:
            want.add(f"{'/'.join(__import__('rules').workdir_root(r))}/runs/2/result.json")
    if not want:
        return None
    got = {t for a in rec["raw"] for t in a.get("told", [])}
    missing = want - got
    return ",".join(sorted(missing)) if missing else None


@prop("A7", "两个独立且都可启动的规则,必须在同一回合都被派出(能并行就要并行派)")
def a7(rec):
    """`independent` in the closure order means nothing forces an order between them, so a
    turn that starts one and settles has left capacity on the table. ADVISORY_ORDER pairs are
    exempt: that edge exists precisely to serialise a cheap detector ahead of an expensive
    stage, and it is a deliberate anti-waste mechanism, not a missed parallel."""
    import rules as R

    def advisory_linked(x, y):
        return y in R.ADVISORY_ORDER.get(x, ()) or x in R.ADVISORY_ORDER.get(y, ())

    if rec["kind"] == "forward-pair" and rec["rel"] == "independent":
        if advisory_linked(rec["a"], rec["b"]):
            return None
        return None if len(opened(rec)) >= 2 else f"only opened {opened(rec)}"
    if rec["kind"] == "inflight" and rec["rel"] == "independent":
        return None if opened(rec) else "the idle one was not admitted"
    if rec["kind"] == "both-fail" and rec.get("owner_rel") == "diff-owner/independent":
        want = expected_owners(rec)
        got = set(opened(rec))
        return None if want <= got else f"opened {sorted(got)}, wanted {sorted(want)}"
    return None


@prop("A6", "a failing rule is never re-verified while its own fix is unanswered")
def a6(rec):
    exp = expected_owners(rec)
    if not exp:
        return None
    answered = {r for r, _ in routed(rec)}
    for a in rec["raw"]:
        if a["action"] != "DISPATCH":
            continue
        # re-verifying a rule that is itself failing, before its owner was dispatched
        for side in ("a", "b"):
            if rec.get(side) == a["rule"] and rec["kind"].endswith("fail"):
                own = space.owner_of(rec[side], rec[f"cat_{side}"])
                if own and own not in answered:
                    return f"{a['rule']} re-verified with {own} unanswered"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--anomaly", default=None)
    ap.add_argument("--show", type=int, default=6)
    args = ap.parse_args()
    recs = load(args.tag)
    by_kind = defaultdict(list)
    for r in recs:
        by_kind[r["kind"]].append(r)

    if args.anomaly:
        stmt, fn = PROPS[args.anomaly]
        hits = [(r, fn(r)) for r in recs]
        hits = [(r, h) for r, h in hits if h]
        print(f"{args.anomaly}: {stmt}\n  violated by {len(hits)}/{len(recs)}\n")
        for r, h in hits[: args.show]:
            print(f"  {r['id']}\n    -> {h}\n       {r['seq']}")
        return

    print(f"=== grid-{args.tag}: {len(recs)} scenarios ===\n")

    print("--- parallelism: pairs both open in one turn ---")
    rows = defaultdict(Counter)
    for r in by_kind["forward-pair"]:
        both = len(opened(r)) >= 2
        overlap = len(r["started"]) >= 2
        rows[r["rel"]][("co-open" if both else "serial", "overlap" if overlap else "-")] += 1
    for rel, c in rows.items():
        print(f"  {rel:<12} " + "  ".join(f"{k[0]}/{k[1]}={n}" for k, n in c.most_common()))

    print("\n--- in-flight admission (one running with a valid proof) ---")
    adm = Counter()
    for r in by_kind["inflight"]:
        started = len(opened(r)) >= 1
        adm[(r["rel"], "admitted" if started else "held")] += 1
    for (rel, verdict), n in sorted(adm.items()):
        print(f"  {rel:<12} {verdict:<9} {n}")

    print("\n--- single failure: first action by category ---")
    for r in sorted(by_kind["single-fail"], key=lambda r: (space.PROOFS.index(r["a"]), r["cat_a"])):
        print(f"  {r['a']:<16} {r['cat_a']:<26} {r['seq'][0]}")

    print("\n--- two failures: first action shape by owner relation ---")
    shape = defaultdict(Counter)
    for r in by_kind["both-fail"]:
        first = r["raw"][0]
        tag = first["action"]
        if tag == "DISPATCH":
            tag = f"DISPATCH x{len(first.get('caused_by', []))}cb"
        shape[r["owner_rel"]][tag] += 1
    for rel in sorted(shape):
        tot = sum(shape[rel].values())
        print(f"  {rel:<28} n={tot:<5} " + "  ".join(f"{k}={v}" for k, v in shape[rel].most_common()))

    print("\n--- properties ---")
    for key, (stmt, fn) in PROPS.items():
        hits = [r for r in recs if fn(r)]
        print(f"  {key}  violated {len(hits):>5}/{len(recs)}   {stmt}")


if __name__ == "__main__":
    main()
