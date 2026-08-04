"""The scenario space, DERIVED from rules.py — never a hand-kept list.

Three questions the grid has to answer exhaustively:

  1. which stage pairs can be in flight together (parallelism), and which of those are
     legitimate (an antichain in the input-closure order) versus accidental;
  2. for a pair, all four verdict combinations (pass/pass, pass/fail, fail/pass, fail/fail);
  3. for every failing stage, every shape its attribution can take — and for two failing
     stages, every combination of the two.

Axis 3 is the one that has to be argued rather than asserted. A failing rule's attribution
can only be one of:

    none | self | outside                       — the three illegal/absent shapes
    env:<O>   for each O in input_closure(R)    — the envelope names a legal owner
    diag:<O>  for each O in input_closure(R)    — a reliable diagnosis names one
    diaglow:<O>, diagnone                       — simulation only (see below)

`input_closure(R)` is the complete set of legal owners, because both writers enforce exactly
that membership (kernel.cmd_diagnose rejects a fix_owner outside it; schedule._disposition
escalates an envelope naming outside it). So the enumeration over the closure is total, not
a sample. The unreliable-diagnosis shapes are restricted to `simulation` on purpose: a
`confidence` field only exists on a triage diagnosis, and simulation-triage is the only
diagnostic any rule dispatches (schedule._disposition's one rule-name literal).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import rules  # noqa: E402

PROOFS = list(rules.FORWARD_PRIORITY)

# One output per rule that NO other rule declares as an input — drifting it invalidates
# that rule's proof and nothing else, which is how a "stale, not failed" state is built.
PRIVATE_OUTPUT = {
    "specification": "Design/specification/spec-review/child.md",
    "simulation-plan": "Verification/simulation-plan/plan-review/review.md",
    "rtl-design": "Design/rtl-design/semantic-review/child.md",
    "lint-cdc": "Design/lint-cdc/lint-report.txt",
    "synthesis": "Design/synthesis/reports/qor.rpt",
    "timing-analysis": "Design/timing-analysis/timing-report.txt",
    "simulation": "Verification/simulation/case-results-summary.md",
    "power-analysis": "Verification/power-analysis/reports_ptpx/S1/power_hier.rpt",
}


def relation(a, b):
    """Position of `a` relative to `b` in the input-closure partial order."""
    if a == b:
        return "same"
    if a in rules.input_closure(b):
        return "upstream"  # a produces (transitively) what b consumes
    if b in rules.input_closure(a):
        return "downstream"
    return "independent"  # an antichain pair — the only legitimately parallel one


def pairs():
    return [
        (a, b) for i, a in enumerate(PROOFS) for b in PROOFS[i + 1 :]
    ]


def categories(rule):
    """Every attribution shape reachable for a failure of `rule`."""
    closure = sorted(rules.input_closure(rule), key=PROOFS.index)
    cats = ["none", "self", "outside"]
    cats += [f"env:{o}" for o in closure]
    cats += [f"diag:{o}" for o in closure]
    if rule == "simulation":  # the only rule with a triage behind it
        cats += [f"diaglow:{o}" for o in closure]
        cats += ["diagnone"]
    return cats


def owner_of(rule, category):
    """The owner this category effectively routes to, or None when it routes nowhere.
    Mirrors what the scheduler concludes — it does not ask the scheduler."""
    kind, _, target = category.partition(":")
    if kind in ("env", "diag"):
        return target
    return None  # none / self / outside / diaglow / diagnone all route nowhere


def owner_relation(rule_a, cat_a, rule_b, cat_b):
    oa, ob = owner_of(rule_a, cat_a), owner_of(rule_b, cat_b)
    if oa is None and ob is None:
        return "neither-routes"
    if oa is None or ob is None:
        return "one-routes"
    if oa == ob:
        return "same-owner"
    return f"diff-owner/{relation(oa, ob)}"


def scenarios():
    """Every scenario, as a flat list of dicts. `kind` selects the builder in run_grid."""
    out = []

    # 1. the reference state: nothing failing, everything valid
    out.append({"kind": "all-valid", "id": "all-valid"})

    # 2. forward parallelism: two proofs stale (never failed) — may both start?
    for a, b in pairs():
        out.append(
            {
                "kind": "forward-pair",
                "id": f"fwd/{a}+{b}",
                "a": a,
                "b": b,
                "rel": relation(a, b),
            }
        )

    # 3. in-flight admission: one rule already running with a VALID proof (the shape a
    #    repair dispatch leaves), the other stale. May the second start under it?
    for a, b in pairs():
        for x, y in ((a, b), (b, a)):
            out.append(
                {
                    "kind": "inflight",
                    "id": f"inflight/{x}-running/{y}-stale",
                    "running": x,
                    "stale": y,
                    "rel": relation(x, y),
                }
            )

    # 4. one failure, every attribution shape
    for r in PROOFS:
        for cat in categories(r):
            out.append(
                {"kind": "single-fail", "id": f"one/{r}/{cat}", "a": r, "cat_a": cat}
            )

    # 5. two failures, every pair, every attribution-shape combination
    for a, b in pairs():
        for ca in categories(a):
            for cb in categories(b):
                out.append(
                    {
                        "kind": "both-fail",
                        "id": f"two/{a}({ca})+{b}({cb})",
                        "a": a,
                        "b": b,
                        "cat_a": ca,
                        "cat_b": cb,
                        "rel": relation(a, b),
                        "owner_rel": owner_relation(a, ca, b, cb),
                    }
                )
    return out


if __name__ == "__main__":
    from collections import Counter

    sc = scenarios()
    print(f"total scenarios: {len(sc)}")
    for k, n in Counter(s["kind"] for s in sc).most_common():
        print(f"  {k:<14} {n}")
    print("\npair relations:")
    for k, n in Counter(relation(a, b) for a, b in pairs()).most_common():
        print(f"  {k:<14} {n}")
    print("\ncategories per rule:")
    for r in PROOFS:
        print(f"  {r:<16} {len(categories(r)):>2}  {' '.join(categories(r))}")
