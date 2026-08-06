#!/usr/bin/env python3
"""Drive every scenario in `space.scenarios()` through the CURRENT scheduler and record
what it does. Writes out/grid-<tag>.jsonl (one record per scenario) — the baseline the
redesign gets diffed against.

    python3 run_grid.py [--tag baseline] [--filter <substring>] [--keep]

Each scenario is a fresh clone of one all-valid module tree, mutated per its kind, then
driven with `fixture.drive` (decide -> real cmd_dispatch -> decide …, never reaping). What
is recorded is the ACTION SEQUENCE, so both questions land in one number set: how many runs
the scheduler will open at once, and what it attaches to each.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixture as F  # noqa: E402
import space  # noqa: E402

SCRATCH = Path(
    os.environ.get(
        "VP_SCRATCH",
        "/tmp/claude-1001/-home-claude-cgy-veripower/"
        "85650174-367e-42e4-858a-74de34816b16/scratchpad/fail-routing-grid",
    )
)
OUT = Path(__file__).parent / "out"


def build(module, sc):
    """Apply the scenario's mutation to a freshly cloned all-valid tree."""
    kind = sc["kind"]
    if kind == "all-valid":
        return
    if kind == "forward-pair":
        for r in (sc["a"], sc["b"]):
            F.mk(module, space.PRIVATE_OUTPUT[r], f"{r}:drifted\n")
        return
    if kind == "inflight":
        # a dispatch with no outcome = in flight; its proof stays valid (the run-1 pass),
        # which is exactly the shape a repair dispatch of a still-valid producer leaves.
        F._dispatch_ev(
            module, sc["running"], 2, F.recorded_inputs(module, sc["running"])
        )
        F.mk(module, space.PRIVATE_OUTPUT[sc["stale"]], "drifted\n")
        return
    if kind == "single-fail":
        F.fail(module, sc["a"], 2, sc["cat_a"])
        return
    if kind == "both-fail":
        F.fail(module, sc["a"], 2, sc["cat_a"])
        F.fail(module, sc["b"], 2, sc["cat_b"])
        return
    raise ValueError(kind)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline")
    ap.add_argument(
        "--filter", default=None, help="only scenarios whose id contains this"
    )
    ap.add_argument("--limit", type=int, default=4, help="max actions per scenario")
    ap.add_argument("--keep", action="store_true", help="keep scenario trees on disk")
    args = ap.parse_args()

    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)

    template = SCRATCH / "_template" / "m"
    template.mkdir(parents=True)
    F.build_baseline(str(template))
    import schedule

    assert schedule.decide(str(template))["action"] == "DONE", (
        "baseline is not all-valid"
    )

    scs = space.scenarios()
    if args.filter:
        scs = [s for s in scs if args.filter in s["id"]]
    out_path = OUT / f"grid-{args.tag}.jsonl"
    t0 = time.time()
    with out_path.open("w") as fh:
        for i, sc in enumerate(scs):
            mdir = SCRATCH / f"s{i:05d}" / "m"
            shutil.copytree(template, mdir)
            build(str(mdir), sc)
            # which rules could start at all in this state — recorded so a property can say
            # "the owner was startable and still was not dispatched" instead of counting a
            # state where the owner's own inputs were unavailable
            import facts as _facts
            import rules as _rules

            evs = _facts.read_events(str(mdir))
            rec_avail = [
                r for r in _rules.RULES if _facts.rule_available(str(mdir), evs, r)
            ]
            seq = F.drive(mdir, limit=args.limit)
            rec = dict(sc)
            rec["available"] = rec_avail
            rec["seq"] = [F.fmt(a) for a in seq]
            rec["raw"] = [
                {
                    k: a[k]
                    for k in (
                        "action",
                        "rule",
                        "execution",
                        "caused_by",
                        "diagnosis_refs",
                        "reason",
                        "told",
                    )
                    if k in a
                }
                for a in seq
            ]
            rec["started"] = F.started_together(seq)
            rec["n_open"] = sum(1 for a in seq if a["action"] == "DISPATCH")
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if not args.keep:
                shutil.rmtree(mdir.parent)
            if (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(scs)}  {time.time() - t0:.0f}s", flush=True)
    print(f"{len(scs)} scenarios -> {out_path}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
