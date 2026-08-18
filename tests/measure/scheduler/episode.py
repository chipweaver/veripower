#!/usr/bin/env python3
"""Episode replay: drive a failing module to convergence and count the runs it costs.

The state grid measures ONE action from ONE state. Waste is a multi-round quantity, so it
needs an executor — and the executor's model is where the 2026-07 measurement went wrong
(assuming any rtl-design round would incidentally fix what
simulation complained about invented a "free fix" tier that does not exist).

The honest model, used here:

    a dispatched rule repairs EXACTLY the defects that this dispatch's `caused_by` names,
    and nothing else. A re-verify of a rule whose defect is still unrepaired fails again,
    with the same attribution its envelope carried the first time.

That is the weakest assumption consistent with the contract: `dispatch.json` is the only
channel through which a round learns what it is about, so a round told nothing fixes
nothing. Anything more generous is an assumption about LLM behaviour, not about the kernel.

Reaping is done by appending the outcome directly rather than through kernel.cmd_reap:
cmd_reap validates the envelope against each stage's own result.schema.json, which would
make this harness a generator of eight synthetic stage envelopes instead of a scheduler
experiment. Dispatch goes through the REAL kernel.cmd_dispatch, so caused_by resolution,
scope, and dispatch.json are the landed code.

    python3 episode.py [--tag baseline] [--filter <substring>]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixture as F  # noqa: E402
import space  # noqa: E402

sys.path.insert(0, str(F.ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import kernel  # noqa: E402
import rules  # noqa: E402
import schedule  # noqa: E402

# Per-stage median wall-clock from the one real run, in minutes.
# Triage never appeared in it — counted separately rather than guessed.
MINUTES = {
    "specification": 22,
    "simulation-plan": 19,
    "rtl-design": 110,
    "lint-cdc": 14,
    "synthesis": 40,
    "timing-analysis": 11,
    "simulation": 54,
    "power-analysis": 22,
    "simulation-triage": 0,
}

SCRATCH = Path(
    os.environ.get(
        "VP_SCRATCH",
        "/tmp/claude-1001/-home-claude-cgy-veripower/"
        "85650174-367e-42e4-858a-74de34816b16/scratchpad/fail-routing-episode",
    )
)
OUT = Path(__file__).parent / "out"


class Defect:
    """One thing that is actually wrong: `rule` fails until `owner` is told about it."""

    def __init__(self, rule, owner, category):
        self.rule, self.owner, self.category = rule, owner, category
        self.fixed = False

    def __repr__(self):
        return f"{self.rule}->{self.owner}{'' if not self.fixed else '(fixed)'}"


def _cb_from_dispatch_json(module, rule, run):
    """(rule, run) of every failure this round's dispatch.json actually names — read back
    from the file the kernel wrote, not from the action that asked for it. Delivery is a
    property of what landed in the workdir: a round can be dispatched at the right owner
    and still be told nothing (a cascade rebuild carries no caused_by)."""
    p = facts.module_root(module) / F.workdir(rule, run) / "dispatch.json"
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for rel in doc.get("caused_by", []):
        parts = Path(rel).parts  # <workdir_root…>/runs/<N>/result.json
        if len(parts) >= 3 and parts[-3] == "runs":
            root = tuple(parts[:-3])
            hit = next((r for r in rules.RULES if rules.workdir_root(r) == root), None)
            if hit:
                out.append((hit, int(parts[-2])))
    return out


def run_episode(module, defects, limit=30):
    """Drive to convergence, tracking DELIVERY as well as cost.

    Two ledgers, because they answer different exit criteria:
      * `occurrences` — every fail outcome that happened. One per defect is the floor; a
        second occurrence of the same defect IS an extra re-run of that stage.
      * `deliveries` — for each occurrence, the steps at which some dispatch.json named it.
        A failure whose owner was rebuilt without being told is NOT delivered."""
    runs, actions = [], []
    occurrences = [
        (d.rule, 2) for d in defects
    ]  # the initial failures, landed at run 2
    occ_step = {o: -1 for o in occurrences}  # they exist before the first decide
    deliveries = {o: [] for o in occurrences}
    told_log = []  # (dispatched rule, coords it was told about) per round that carried any
    for step in range(limit):
        a = schedule.decide(str(module))
        actions.append(F.fmt(a))
        if a["action"] != "DISPATCH":
            return (
                runs,
                actions,
                a["action"],
                occurrences,
                occ_step,
                deliveries,
                told_log,
            )
        rule = a["rule"]
        d = kernel.cmd_dispatch(
            str(module),
            rule,
            a.get("diagnosis_refs"),
            a.get("params"),
            [tuple(c) for c in a.get("caused_by", [])],
        )
        if not d["ok"]:
            actions.append("X:" + d["error"])
            return (
                runs,
                actions,
                "DISPATCH_REJECTED",
                occurrences,
                occ_step,
                deliveries,
                told_log,
            )
        run = d["run"]
        runs.append((rule, run))

        # what this round was actually told — the ONLY thing it can repair, and the only
        # thing that counts as the conclusion having reached a stage
        told = _cb_from_dispatch_json(module, rule, run)
        for coord in told:
            deliveries.setdefault(coord, []).append(step)
        if told:
            told_log.append((rule, [f"{r}:{n}" for r, n in told]))
        told_rules = {r for r, _ in told}
        for defect in defects:
            if defect.owner == rule and defect.rule in told_rules:
                defect.fixed = True

        if rule == "simulation-triage":
            _land_triage(module, run, defects)
            continue
        unfixed = {d.rule: d for d in defects if not d.fixed}
        if rule in unfixed:
            F.fail(module, rule, run, unfixed[rule].category, dispatched=True)
            occurrences.append((rule, run))
            occ_step[(rule, run)] = step
            deliveries.setdefault((rule, run), [])
        else:
            F.land_pass(module, rule, run, tag=f"e{run}x{len(runs)}", dispatched=True)
    return runs, actions, "LIMIT", occurrences, occ_step, deliveries, told_log


def _land_triage(module, run, defects):
    """Triage has no proof: its outcome is a pass plus the diagnosis it derived. Models a
    complete, high-confidence analysis of simulation's unrepaired defect."""
    facts.append_event(
        module,
        {
            "type": "outcome",
            "rule": "simulation-triage",
            "run": run,
            "verdict": "pass",
            "outputs": {},
            "proofs": [],
            "tool_versions": {},
        },
        F.TS,
    )
    sim = next((d for d in defects if d.rule == "simulation" and not d.fixed), None)
    if sim is None:
        return
    hit = schedule._latest_fail(facts.read_events(str(module)), "simulation")
    facts.append_event(
        module,
        {
            "type": "diagnosis",
            "id": f"d-triage-{run}",
            "subject": {"proof": "simulation", "outcome_run": hit[1]["run"]},
            "attribution": sim.owner,
            "fix_owner": sim.owner,
            "evidence": [f"{F.workdir('simulation-triage', run)}/result.json"],
            "confidence": "high",
            "source": "triage",
        },
        F.TS,
    )


def episodes():
    """Two families.

    ENVELOPE (`env:`): the failing stage names its own fix owner. One failing rule, then
    every pair. A `diag:` variant is not generated — a human diagnosis binds to one
    outcome_run, so every re-fail would need a human back in the loop, which is not a
    scheduler property.

    TRIAGE (`none:`): simulation's envelope names nobody, so the diagnostic runs and its
    reap mints the attribution. This is the path `simulation/SKILL.md` calls "an answer
    rather than a shrug", and until 2026-08-05 the episode set never once entered it —
    simulation-triage ran zero times across both tags, so every acceptance number spoke
    only for the envelope family."""
    out = []
    for r in space.PROOFS:
        for o in sorted(rules.input_closure(r), key=space.PROOFS.index):
            out.append({"id": f"one/{r}->{o}", "defects": [(r, o)]})
    for a, b in space.pairs():
        for oa in sorted(rules.input_closure(a), key=space.PROOFS.index):
            for ob in sorted(rules.input_closure(b), key=space.PROOFS.index):
                out.append(
                    {
                        "id": f"two/{a}->{oa}+{b}->{ob}",
                        "defects": [(a, oa), (b, ob)],
                        "pair_rel": space.relation(a, b),
                        "owner_rel": "same-owner"
                        if oa == ob
                        else f"diff-owner/{space.relation(oa, ob)}",
                    }
                )

    # triage family: simulation cannot attribute its own failure, so the diagnostic has to
    # find the owner first. Paired against every envelope defect too, because the
    # interesting question is what happens to an un-analysed failure while a sibling repair
    # lands under it.
    for o in sorted(rules.input_closure("simulation"), key=space.PROOFS.index):
        out.append(
            {
                "id": f"one/simulation~triage->{o}",
                "defects": [("simulation", o)],
                "triage": ["simulation"],
            }
        )
        for r in space.PROOFS:
            if r == "simulation":
                continue
            for oo in sorted(rules.input_closure(r), key=space.PROOFS.index):
                out.append(
                    {
                        "id": f"two/simulation~triage->{o}+{r}->{oo}",
                        "defects": [("simulation", o), (r, oo)],
                        "triage": ["simulation"],
                        "pair_rel": space.relation("simulation", r),
                        "owner_rel": "same-owner"
                        if o == oo
                        else f"diff-owner/{space.relation(o, oo)}",
                    }
                )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--filter", default=None)
    args = ap.parse_args()
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)

    template = SCRATCH / "_template" / "m"
    template.mkdir(parents=True)
    F.build_baseline(str(template))
    assert schedule.decide(str(template))["action"] == "DONE"

    eps = episodes()
    if args.filter:
        eps = [e for e in eps if args.filter in e["id"]]
    path = OUT / f"episodes-{args.tag}.jsonl"
    t0 = time.time()
    with path.open("w") as fh:
        for i, ep in enumerate(eps):
            mdir = SCRATCH / f"e{i:05d}" / "m"
            shutil.copytree(template, mdir)
            # a rule listed in `triage` names nobody, so its owner has to be discovered
            triaged = set(ep.get("triage", []))
            defects = [
                Defect(r, o, "none" if r in triaged else f"env:{o}")
                for r, o in ep["defects"]
            ]
            for d in defects:  # land the initial failures, FORWARD order
                F.fail(str(mdir), d.rule, 2, d.category)
            runs, actions, ending, occ, occ_step, deliv, told_log = run_episode(
                str(mdir), defects
            )
            # a delivery is LATE when the failing rule was re-verified before its own
            # conclusion reached anyone — that re-verify is the extra run
            owner_of = {d.rule: d.owner for d in defects}
            missed_nearest = []
            late, undelivered = [], []
            for frule, frun in occ:
                steps = deliv.get((frule, frun), [])
                first_reverify = next(
                    (i for i, (r, n) in enumerate(runs) if r == frule and n > frun),
                    None,
                )
                if not steps:
                    undelivered.append(f"{frule}:{frun}")
                elif first_reverify is not None and first_reverify < steps[0]:
                    late.append(f"{frule}:{frun}")
                # nearest injection: no round of the owner may run between this failure
                # landing and this failure being handed to it
                own = owner_of.get(frule)
                since = occ_step[(frule, frun)]
                first_deliv = steps[0] if steps else len(runs)
                if own and any(
                    r == own and since < i < first_deliv
                    for i, (r, _) in enumerate(runs)
                ):
                    missed_nearest.append(f"{frule}:{frun}->{own}")
            rec = dict(ep)
            rec.update(
                {
                    "runs": [f"{r}:{n}" for r, n in runs],
                    "n_runs": len(runs),
                    "minutes": sum(MINUTES[r] for r, _ in runs),
                    "triage_runs": sum(1 for r, _ in runs if r == "simulation-triage"),
                    "triage": ep.get("triage", []),
                    "ending": ending,
                    "actions": actions,
                    "occurrences": [f"{r}:{n}" for r, n in occ],
                    "extra_failures": len(occ) - len(defects),
                    "undelivered": undelivered,
                    "missed_nearest": missed_nearest,
                    "late": late,
                    "told_log": [{"owner": o, "coords": c} for o, c in told_log],
                    # an owner told about this defect set more than once is a merge that
                    # did not happen: that stage ran twice where one round would do
                    "merge_misses": sum(
                        n - 1
                        for n in collections.Counter(o for o, _ in told_log).values()
                        if n > 1
                    ),
                }
            )
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            shutil.rmtree(mdir.parent)
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(eps)}  {time.time() - t0:.0f}s", flush=True)
    print(f"{len(eps)} episodes -> {path}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
