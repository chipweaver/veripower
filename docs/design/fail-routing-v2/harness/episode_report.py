#!/usr/bin/env python3
"""Episode cost vs the theoretical minimum for the same defect set.

Minimum = every owner dispatched ONCE (carrying all of its complaints) + every proof that
its products invalidate re-verified ONCE. Both terms are derived from the registry, so the
baseline is not "what the scheduler did on a good day" — it is the floor the DAG imposes.

    python3 episode_report.py [--tag baseline] [--worst 10] [--diff other-tag]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import space  # noqa: E402
from episode import MINUTES, OUT  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "framework" / "scripts"))
import rules  # noqa: E402


def floor_runs(owners):
    """The run set an ideal scheduler would execute: every rule that is an owner OR sits
    downstream of one, ONCE each.

    A set, not a concatenation: a rule that is both (rtl-design owning one complaint while
    specification owns another) still runs once — its single round carries the rebuild its
    upstream forced AND the complaint it owns. Counting it twice understates the waste of
    exactly the class where two owners sit on one chain."""
    owners = set(owners)
    down = {r for r in space.PROOFS if any(o in rules.input_closure(r) for o in owners)}
    return sorted(owners | down, key=space.PROOFS.index)


def load(tag):
    recs = [json.loads(x) for x in (OUT / f"episodes-{tag}.jsonl").open()]
    for r in recs:
        owners = [x.split("->")[1] for x in r["id"].split("/", 1)[1].split("+")]
        fr = floor_runs(owners)
        # a failure whose stage cannot attribute it needs one analysis round before anyone
        # can be dispatched — that round is part of the floor, not waste
        r["floor_runs"] = len(fr) + len(r.get("triage", []))
        r["floor_min"] = sum(MINUTES[x] for x in fr)
        r["waste_runs"] = r["n_runs"] - r["floor_runs"]
        r["waste_min"] = r["minutes"] - r["floor_min"]
    return recs


EXITS = {
    # key: (statement, predicate that a PASSING episode satisfies)
    "E1": ("任务不丢:每个缺陷最终被修复,回合收敛", lambda r: r["ending"] == "DONE"),
    "E2": ("结论不丢:每条失败的信封都送达过某个 owner 的 dispatch.json",
           lambda r: not r["undelivered"]),
    "E3": ("形态正确:同 owner 合并为一轮,不同 owner 各自一轮",
           lambda r: r["merge_misses"] == 0),
    "E4": ("无额外重跑:每个缺陷只失败一次", lambda r: r["extra_failures"] == 0),
    "E6": ("最近注入:失败与它被交付之间,owner 没有白跑过一轮",
           lambda r: not r["missed_nearest"]),
    "E5": ("无额外轮次:总轮数等于 registry 下界", lambda r: r["waste_runs"] == 0),
}


def exit_table(recs, label):
    """The exit criteria, stated as what a stage receives rather than what was dispatched."""
    print(f"=== {label}: 出口判据 ===")
    groups = [("单 fail", [r for r in recs if r["id"].startswith("one/")])]
    two = [r for r in recs if r["id"].startswith("two/")]
    for key in sorted({(r["owner_rel"]) for r in two}):
        groups.append((f"双 fail {key}", [r for r in two if r["owner_rel"] == key]))
    hdr = "  ".join(f"{k:>5}" for k in EXITS)
    print(f"  {'类别':<26}{'n':>4}   {hdr}")
    for name, rs in groups:
        if not rs:
            continue
        cells = []
        for key, (_, ok) in EXITS.items():
            cells.append(f"{sum(1 for r in rs if ok(r)):>5}")
        print(f"  {name:<26}{len(rs):>4}   " + "  ".join(cells))
    print("\n  判据:")
    for key, (stmt, _) in EXITS.items():
        n = sum(1 for r in recs if EXITS[key][1](r))
        print(f"    {key} {n:>4}/{len(recs)}  {stmt}")
    return two


def summarize(recs, label):
    two = [r for r in recs if r["id"].startswith("two/")]
    one = [r for r in recs if r["id"].startswith("one/")]
    print(f"=== {label}: {len(recs)} episodes, endings "
          f"{dict(collections.Counter(r['ending'] for r in recs))} ===")
    print(f"  single-defect ({len(one)}): waste "
          f"{dict(collections.Counter(r['waste_runs'] for r in one))}")
    g = collections.defaultdict(list)
    for r in two:
        g[(r["pair_rel"], r["owner_rel"])].append(r)
    print(f"\n  {'pair':<12}{'owners':<26}{'n':>4}{'clean':>7}{'med+runs':>10}"
          f"{'med+min':>9}{'tot+min':>9}")
    for k in sorted(g):
        v = g[k]
        wr = sorted(x["waste_runs"] for x in v)
        wm = sorted(x["waste_min"] for x in v)
        print(f"  {k[0]:<12}{k[1]:<26}{len(v):>4}"
              f"{sum(1 for x in wr if x == 0):>7}{wr[len(wr) // 2]:>10}"
              f"{wm[len(wm) // 2]:>9}{sum(wm):>9}")
    print(f"\n  two-defect: {sum(1 for r in two if r['waste_runs'] > 0)}/{len(two)} waste "
          f"at least one run; total {sum(r['waste_min'] for r in two)} min over "
          f"{sum(r['floor_min'] for r in two)} min of floor")
    return two


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--diff", default=None)
    ap.add_argument("--worst", type=int, default=8)
    args = ap.parse_args()
    recs = load(args.tag)
    exit_table(recs, args.tag)
    print()
    two = summarize(recs, args.tag)
    print(f"\n  worst {args.worst}:")
    for r in sorted(two, key=lambda x: -x["waste_min"])[: args.worst]:
        print(f"    +{r['waste_min']:>3}min +{r['waste_runs']} runs  {r['id']}")
        print(f"        {r['runs']}")

    if args.diff:
        new = {r["id"]: r for r in load(args.diff)}
        print(f"\n=== diff {args.tag} -> {args.diff} ===")
        better = worse = same = 0
        for r in recs:
            n = new.get(r["id"])
            if n is None:
                continue
            d = n["waste_min"] - r["waste_min"]
            if d < 0:
                better += 1
            elif d > 0:
                worse += 1
                print(f"  WORSE +{d}min  {r['id']}\n    {r['runs']}\n    {n['runs']}")
            else:
                same += 1
        print(f"  better={better} same={same} worse={worse}")
        print(f"  total waste {sum(r['waste_min'] for r in recs)} -> "
              f"{sum(new[r['id']]['waste_min'] for r in recs if r['id'] in new)} min")


if __name__ == "__main__":
    main()
