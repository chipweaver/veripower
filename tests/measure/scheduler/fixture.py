"""Self-contained scheduler fixture — a real module tree driven by the real kernel.

No external data: the 2026-07 harness read /home/mhc/backup/{asic,eval}, which no longer
exists. Everything here is synthesized from `rules.py` itself, so the fixture cannot drift
from the registry the way a hand-copied artifact map does.

Fidelity, stated once so the grid can be read honestly:
  * schedule / facts / rules / kernel.cmd_dispatch: the landed code, no stubs.
  * proof events are appended directly (facts.append_event) with REAL disk fingerprints —
    the same idiom tests/unit/test_schedule.py uses. Stage execution is not simulated:
    a scenario is a STATE, and what is measured is the action `decide` takes from it.
  * a failing run gets both a canonical result.json (what schedule._declared_owner reads)
    and a per-run runs/<N>/result.json (what kernel.cmd_dispatch --caused-by resolves),
    so a routed dispatch goes through the real resolution path rather than a mocked one.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import kernel  # noqa: E402
import rules  # noqa: E402
import schedule  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"

# One declared output per selector of every rule, so every input glob of every consumer
# resolves. Kept in registry shape (module-relative) — the fixture's only hand-written map.
OUTPUTS = {
    "specification": [
        "Design/specification/design.md",
        "Design/specification/child.md",
        "Design/specification/manifest.json",
        "Design/specification/ppa.json",
        "Design/specification/clocks.json",
        "Design/specification/features.json",
        "Design/specification/check-hints/c.json",
        "Design/specification/top-io.json",
        "Design/specification/interconnects.json",
        "Design/specification/spec-review/child.md",
        "Design/specification/constraints/top.sdc",
        "Design/specification/constraints/top.sgdc",
    ],
    "simulation-plan": [
        "Verification/simulation-plan/verification-plan.md",
        "Verification/simulation-plan/tb-scaffold.json",
        "Verification/simulation-plan/sequences.json",
        "Verification/simulation-plan/power-scenarios.json",
        "Verification/simulation-plan/plan-review/review.md",
    ],
    "rtl-design": [
        "Design/rtl-design/matvec.v",
        "Design/rtl-design/rtl-files.json",
        "Design/rtl-design/constraint-annotations.json",
        "Design/rtl-design/semantic-review/child.md",
    ],
    "lint-cdc": [
        "Design/lint-cdc/lint-report.txt",
        "Design/lint-cdc/cdc-report.txt",
        "Design/lint-cdc/lint-violations.json",
        "Design/lint-cdc/cdc-violations.json",
        "Design/lint-cdc/scripts/constraints.sgdc",
        "Design/lint-cdc/scripts/local.sgdc",
        "Design/lint-cdc/scripts/waiver.tcl",
    ],
    "synthesis": [
        "Design/synthesis/out/top_syn.v",
        "Design/synthesis/out/top_syn.sdc",
        "Design/synthesis/out/top_syn.sdf",
        "Design/synthesis/reports/qor.rpt",
        "Design/synthesis/constraints.sdc",
        "Design/synthesis/constraints.local.sdc",
    ],
    "timing-analysis": ["Design/timing-analysis/timing-report.txt"],
    "simulation": [
        "Verification/simulation/case-results-summary.md",
        "Verification/simulation/conformance-review.md",
        "Verification/simulation/env.sh",
        "Verification/simulation/filelist.f",
        "Verification/simulation/rtl_filelist.f",
        "Verification/simulation/tb/uvm/agent.sv",
        "Verification/simulation/tb/uvm/refmodel/ref.sv",
    ],
    "power-analysis": ["Verification/power-analysis/reports_ptpx/S1/power_hier.rpt"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mk(module, rel, content):
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def fp(module, rel):
    return facts.fingerprint(facts.module_root(module) / rel)


def workdir(rule, run):
    return "/".join(rules.workdir_root(rule)) + f"/runs/{run}"


def recorded_inputs(module, rule):
    """Current disk fingerprints of the rule's declared, non-self input globs."""
    root = facts.module_root(module)
    rec = {}
    for globs in rules.RULES[rule].inputs.values():
        for g in globs:
            if rules.producer_of(g) == rule:
                continue
            for p in sorted(root.glob(g)):
                if p.is_file():
                    rec[str(p.relative_to(root))] = facts.fingerprint(p)
    return rec


def _dispatch_ev(module, rule, run, inputs):
    facts.append_event(
        module,
        {
            "type": "dispatch",
            "rule": rule,
            "run": run,
            "workdir": workdir(rule, run),
            "inputs": inputs,
            "params": {},
        },
        TS,
    )


def _outcome_ev(module, rule, run, verdict, outputs, inputs):
    r = rules.RULES[rule]
    facts.append_event(
        module,
        {
            "type": "outcome",
            "rule": rule,
            "run": run,
            "verdict": verdict,
            "outputs": outputs,
            "proofs": [
                {
                    "name": rule,
                    "verdict": verdict,
                    "inputs": inputs,
                    "oracle": {"ref": r.oracle[0], "grade": r.oracle[1]},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )


def land_pass(module, rule, run=1, tag=None, dispatched=False):
    """Dispatch+pass: write declared outputs, record inputs/outputs at disk fingerprints.

    `dispatched=True` when the caller already opened this run through kernel.cmd_dispatch
    (the episode loop does) — appending a second dispatch event for the same (rule, run)
    would double-count facts.runs_of and put a duplicate coordinate in the log that any
    dispatch-scanning predicate would read twice."""
    marker = tag if tag is not None else f"r{run}"
    for rel in OUTPUTS[rule]:
        mk(module, rel, f"{rule}:{rel}:{marker}\n")
    inputs = recorded_inputs(module, rule)
    outputs = {rel: fp(module, rel) for rel in OUTPUTS[rule]}
    if not dispatched:
        _dispatch_ev(module, rule, run, inputs)
    _outcome_ev(module, rule, run, "pass", outputs, inputs)


# ── failure shapes ────────────────────────────────────────────────────────────────
# A category names WHERE the attribution comes from and WHAT it points at:
#   none          envelope names nobody
#   self          envelope names the failing rule itself
#   outside       envelope names a rule outside the failing rule's input closure
#   env:<O>       envelope names O (legal, O in the input closure)
#   diag:<O>      a reliable diagnosis names O (triage/high for simulation, human elsewhere)
#   diaglow:<O>   a triage diagnosis names O with confidence=low (simulation only)
#   diagnone      a triage diagnosis with no fix_owner (self-pointing root cause; sim only)


def outside_target(rule):
    """A deterministic rule outside `rule`'s input closure (and not itself)."""
    closure = rules.input_closure(rule)
    for cand in rules.FORWARD_PRIORITY:
        if cand != rule and cand not in closure:
            return cand
    return None


def fail(module, rule, run, category, dispatched=False):
    """Dispatch+fail `rule` at `run`, shaped by `category`. Writes the canonical envelope
    AND the per-run one, then (for diag* categories) appends the diagnosis event.
    `dispatched=True` when the caller already opened the run (see land_pass)."""
    inputs = recorded_inputs(module, rule)
    if not dispatched:
        _dispatch_ev(module, rule, run, inputs)

    kind, _, target = category.partition(":")
    owner = {"self": rule, "outside": outside_target(rule)}.get(kind)
    if kind == "env":
        owner = target
    envelope = {
        "schema_version": "1.0",
        "status": "fail",
        "produced_at": now_iso(),
        "artifacts": [],
        "stage_specific": {"fail_reason": f"synthetic {category}"},
    }
    if owner:
        envelope["stage_specific"]["fix_owner"] = owner
    body = json.dumps(envelope, indent=2)
    mk(module, "/".join(rules.workdir_root(rule)) + "/result.json", body)
    mk(module, workdir(rule, run) + "/result.json", body)

    _outcome_ev(module, rule, run, "fail", {}, inputs)

    if kind in ("diag", "diaglow", "diagnone"):
        ev = {
            "type": "diagnosis",
            "id": f"d-{rule}-{run}",
            "subject": {"proof": rule, "outcome_run": run},
            "attribution": target or rule,
            "evidence": [f"{workdir('simulation-triage', 1)}/result.json"],
        }
        if kind != "diagnone":
            ev["fix_owner"] = target
        if rule == "simulation":
            ev["source"] = "triage"
            ev["confidence"] = "low" if kind == "diaglow" else "high"
        else:
            ev["source"] = "human"
            ev["provenance"] = "harness"
            ev["reason"] = f"synthetic {category}"
        facts.append_event(module, ev, TS)


# ── baseline tree + cloning ───────────────────────────────────────────────────────


def build_baseline(module):
    """All eight proofs valid at run 1. FORWARD order, so each rule's upstream outputs
    exist on disk when its inputs are recorded."""
    mk(module, "brainstorm.md", "b1\n")
    for rule in rules.FORWARD_PRIORITY:
        land_pass(module, rule, 1)


def clone(src, dst):
    shutil.copytree(src, dst)
    return dst


# ── the orchestrator loop, executor removed ───────────────────────────────────────


def drive(module, limit=6):
    """decide -> execute the DISPATCH -> decide again, never reaping. What a run WOULD
    produce is not simulated: this measures how many runs the scheduler is willing to have
    open at once, and what it attaches to each — the parallelism and routing questions.
    Stops at the first non-DISPATCH action."""
    seq = []
    for _ in range(limit):
        a = schedule.decide(str(module))
        seq.append(a)
        if a["action"] != "DISPATCH":
            break
        d = kernel.cmd_dispatch(
            str(module),
            a["rule"],
            a.get("diagnosis_refs"),
            a.get("params"),
            [tuple(c) for c in a.get("caused_by", [])],
        )
        if not d["ok"]:
            seq.append({"action": "DISPATCH_REJECTED", "reason": d["error"]})
            break
        # delivery is what LANDED in the workdir, not what the action asked for
        try:
            doc = json.loads((Path(d["workdir"]) / "dispatch.json").read_text())
        except (OSError, ValueError):
            doc = {}
        a["told"] = doc.get("caused_by", [])
    return seq


def started_together(seq):
    """Which dispatches of one turn actually START before the turn blocks: the leading run
    of `task` dispatches plus the FIRST main-thread one (a main-thread Skill() runs to
    completion inside the turn). Per skills/design-flow/SKILL.md — a semantic derivation,
    not a wall-clock measurement."""
    out = []
    for a in seq:
        if a["action"] != "DISPATCH":
            break
        out.append(a["rule"])
        if a["execution"] == "main-thread":
            break
    return out


def fmt(a):
    """One action as a compact grid cell."""
    if a["action"] == "DISPATCH":
        tag = "D" if a["execution"] == "task" else "M"
        cb = ",".join(f"{r}:{n}" for r, n in a.get("caused_by", []))
        refs = ",".join(a.get("diagnosis_refs", []))
        extra = f"[{cb}]" if cb else ""
        extra += f"<{refs}>" if refs else ""
        return f"{tag}:{a['rule']}{extra}"
    if a["action"] == "YIELD":
        return "Y:" + ",".join(f"{f['rule']}:{f['run']}" for f in a["in_flight"])
    if a["action"] == "ESCALATE":
        return "E:" + a["reason"]
    if a["action"] == "DISPATCH_REJECTED":
        return "X:" + a["reason"]
    return a["action"]
