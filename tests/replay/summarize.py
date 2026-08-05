#!/usr/bin/env python3
"""Two tags side by side: the divergence sets, and every point where they differ.

Reads ../../out/replay-<tag>.jsonl (written by replay.py) and writes ../../out/replay.txt.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
# v1 = main's scheduler, v4 = this branch's.
TAGS = ("v1", "v4")


def load(tag):
    p = OUT / f"replay-{tag}.jsonl"
    return {
        r["k"]: r for r in (json.loads(ln) for ln in p.read_text().splitlines() if ln)
    }


def main():
    d = {t: load(t) for t in TAGS}
    lines = []
    w = lines.append

    w("=== agreement with the real run ===")
    for t in TAGS:
        n = sum(r["agree"] for r in d[t].values())
        w(f"  {t}: {n}/{len(d[t])} decision points")
    sets = {t: {k for k, r in d[t].items() if not r["agree"]} for t in TAGS}
    a, b = sets[TAGS[0]], sets[TAGS[1]]
    w(f"  {TAGS[0]} diverges at: {sorted(a)}")
    w(f"  {TAGS[1]} diverges at: {sorted(b)}")
    w(
        f"  {TAGS[1]} subset of {TAGS[0]}: {b < a}   fixes={sorted(a - b)}   introduces={sorted(b - a)}"
    )

    w("")
    w("=== every point where the two schedulers act differently ===")
    for k in sorted(d[TAGS[0]]):
        x, y = d[TAGS[0]][k], d[TAGS[1]][k]
        if x["decide"] == y["decide"]:
            continue
        w(f"  k={k:3d} {x['ts']}  real = {x['real']}")
        for t, r in ((TAGS[0], x), (TAGS[1], y)):
            w(f"        {t} = {r['decide']}")

    w("")
    w("=== full trace (current tag last) ===")
    w(f"  {'k':>3s} {'ts':19s} {'real':30s} {TAGS[0]:34s} {TAGS[1]}")
    for k in sorted(d[TAGS[0]]):
        x, y = d[TAGS[0]][k], d[TAGS[1]][k]
        mark = "  " if y["agree"] else " !"
        w(
            f" {mark}{k:3d} {x['ts']} {x['real']:30s} {x['decide'][:33]:34s} {y['decide'][:60]}"
        )

    text = "\n".join(lines) + "\n"
    (OUT / "replay.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
