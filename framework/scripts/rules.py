"""VeriPower rule registry — the single SSoT for what the kernel schedules.

One Rule = one kernel-scheduled unit. Artifact-level input/output selectors are
module-relative canonical-path globs. The dependency graph is DERIVED from these
(producer_of): no separate stage-view DAG is maintained. Dependency-light leaf —
import the bare way (`import rules`)."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    name: str
    stage: str
    skill: str
    execution: str  # "task" | "main-thread"
    workdir_root: tuple[str, ...]
    inputs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    outputs: tuple[str, ...] = ()
    cache: tuple[str, ...] = ()
    proof: str | None = None
    oracle: tuple[str, str] | None = None  # (ref, grade)
    oracle_selector: str | None = None  # proposed-oracle content selector (workdir-root-relative glob)
    params: tuple[str, ...] = ()


RULES: dict[str, Rule] = {
    "specification": Rule(
        name="specification", stage="specification", skill="veripower:specification",
        execution="main-thread", workdir_root=("Design", "specification"),
        inputs={"brainstorm": ("brainstorm.md",)},
        outputs=("design.md", "*.md",  # *.md = the per-child <child>.md docs (N>=1) — real
                 # promoted products; sim-plan/rtl-design consume them as inputs
                 "manifest.json", "coverage.json", "ppa.json",
                 "spec-review.json", "constraints/*.sdc", "constraints/*.sgdc"),
        proof="specification", oracle=("spec-review", "proposed"),
        oracle_selector="spec-review.json", params=("directive",),
    ),
    "simulation-plan": Rule(
        name="simulation-plan", stage="simulation-plan", skill="veripower:simulation-plan",
        execution="main-thread", workdir_root=("Verification", "simulation-plan"),
        inputs={"design": ("Design/specification/design.md",),
                "manifest": ("Design/specification/manifest.json",),
                "children": ("Design/specification/*.md",)},
        outputs=("verification-plan.md", "scaffold-specification.json", "plan-review.json"),
        cache=("plan-data.json",),
        proof="simulation-plan", oracle=("plan-review", "proposed"),
        oracle_selector="plan-review.json", params=("directive",),
    ),
    "rtl-design": Rule(
        name="rtl-design", stage="rtl-design", skill="veripower:rtl-design",
        execution="main-thread", workdir_root=("Design", "rtl-design"),
        inputs={"design": ("Design/specification/design.md",),
                "manifest": ("Design/specification/manifest.json",),
                "children": ("Design/specification/*.md",)},
        outputs=("*.v", "filelist.txt", "README.md", "semantic-review.json"),
        proof="rtl-design", oracle=("semantic-review", "proposed"),
        oracle_selector="semantic-review.json", params=("directive",),
    ),
    "lint-cdc": Rule(
        name="lint-cdc", stage="lint-cdc", skill="veripower:lint-cdc",
        execution="task", workdir_root=("Design", "lint-cdc"),
        inputs={"rtl": ("Design/rtl-design/*.v", "Design/rtl-design/filelist.txt"),
                "rtl_doc": ("Design/rtl-design/README.md",),
                "sgdc_seed": ("Design/specification/constraints/*.sgdc",),
                "waiver": ("Design/lint-cdc/scripts/waiver.tcl",)},
        outputs=("lint-report.txt", "cdc-report.txt", "lint-violations.json",
                 "cdc-violations.json", "scripts/constraints.sgdc", "scripts/waiver.tcl"),
        cache=("scripts/constraints.sgdc",),
        proof="lint-cdc", oracle=("spyglass-ruleset", "tool"), params=("directive",),
    ),
    "synthesis": Rule(
        name="synthesis", stage="synthesis", skill="veripower:synthesis",
        execution="task", workdir_root=("Design", "synthesis"),
        inputs={"rtl": ("Design/rtl-design/*.v", "Design/rtl-design/filelist.txt"),
                "rtl_doc": ("Design/rtl-design/README.md",),
                "sdc": ("Design/specification/constraints/*.sdc",),
                "ppa": ("Design/specification/ppa.json",)},
        outputs=("out/*_syn.v", "out/*_syn.sdc", "out/*_syn.sdf", "reports/qor.rpt", "constraints.sdc"),
        proof="synthesis", oracle=("dc-shell", "tool"), params=("directive",),
    ),
    "timing-analysis": Rule(
        name="timing-analysis", stage="timing-analysis", skill="veripower:timing-analysis",
        execution="task", workdir_root=("Design", "timing-analysis"),
        inputs={"netlist": ("Design/synthesis/out/*_syn.v",),
                "sdc": ("Design/synthesis/out/*_syn.sdc",)},
        outputs=("timing-report.txt", "timing-actual.json"),
        proof="timing-analysis", oracle=("pt-shell", "tool"), params=("directive",),
    ),
    "simulation": Rule(
        name="simulation", stage="simulation", skill="veripower:simulation",
        execution="main-thread", workdir_root=("Verification", "simulation"),
        inputs={"rtl": ("Design/rtl-design/*.v", "Design/rtl-design/filelist.txt"),
                # NOT rtl_doc/README: simulation's only README use was top inference, now
                # read from manifest.module (§4.3); README prose is not a sim verdict-dependency,
                # so binding it only caused README-only edits to falsely invalidate (D6/G4).
                "plan": ("Verification/simulation-plan/verification-plan.md",),
                "scaffold": ("Verification/simulation-plan/scaffold-specification.json",)},
        outputs=("case-results-summary.md", "conformance-review.json",
                 "env.sh", "filelist.f", "rtl_filelist.f", "tb/uvm/*"),  # TB env: real
                 # promoted products (sim/result.py enumerate_artifacts) — power-analysis consumes them
        proof="simulation", oracle=("tb-refmodel", "proposed"),
        oracle_selector="tb/uvm/refmodel/*",  # pin endorses the JUDGE itself (spec §2) —
        # survives runs; content drift (LLM regenerates refmodel) drops the pin at reap
        params=("directive",),
    ),
    "power-analysis": Rule(
        name="power-analysis", stage="power-analysis", skill="veripower:power-analysis",
        execution="task", workdir_root=("Verification", "power-analysis"),
        inputs={"netlist": ("Design/synthesis/out/*_syn.v", "Design/synthesis/out/*_syn.sdc",
                            "Design/synthesis/out/*_syn.sdf"),
                "tb_env": ("Verification/simulation/env.sh",
                           "Verification/simulation/filelist.f",
                           "Verification/simulation/rtl_filelist.f",
                           "Verification/simulation/tb/uvm/*"),
                "scaffold": ("Verification/simulation-plan/scaffold-specification.json",),
                "ppa": ("Design/specification/ppa.json",)},
        outputs=("reports_ptpx/*/power_hier.rpt",),
        proof="power-analysis", oracle=("pt-shell", "tool"), params=("directive",),
    ),
    "frontend-signoff": Rule(
        name="frontend-signoff", stage="frontend-signoff", skill="veripower:frontend-signoff",
        execution="task", workdir_root=("frontend-signoff",),
        inputs={"design": ("Design/specification/design.md",),
                "lint": ("Design/lint-cdc/lint-report.txt", "Design/lint-cdc/cdc-report.txt"),
                "sim": ("Verification/simulation/case-results-summary.md",),
                "timing": ("Design/timing-analysis/timing-report.txt",),
                "qor": ("Design/synthesis/reports/qor.rpt",),
                "power": ("Verification/power-analysis/reports_ptpx/*/power_hier.rpt",),
                "manifest": ("Design/specification/manifest.json",)},
        outputs=("checklist.md", "traceability.md"),
        proof="frontend-signoff", oracle=("signoff-aggregator", "tool"), params=("directive",),
    ),
    "simulation-triage": Rule(
        name="simulation-triage", stage="simulation-triage", skill="veripower:simulation-triage",
        execution="task", workdir_root=("Verification", "simulation-triage"),
        inputs={}, outputs=(), cache=(), proof=None, oracle=None, params=("sim_run",),
    ),
}

FORWARD_PRIORITY: list[str] = [
    "specification", "simulation-plan", "rtl-design", "lint-cdc", "synthesis",
    "timing-analysis", "simulation", "power-analysis", "frontend-signoff",
]

PIPELINE_INPUTS: tuple[str, ...] = ("brainstorm.md",)

ADVISORY_ORDER: dict[str, tuple[str, ...]] = {
    "synthesis": ("lint-cdc",),
    "power-analysis": ("timing-analysis",),
}


def _canonical_output_globs(rule: Rule) -> list[str]:
    """Rule outputs expressed as module-relative globs (prefixed by workdir_root)."""
    base = "/".join(rule.workdir_root)
    return [f"{base}/{o}" for o in rule.outputs]


def producer_of(artifact_relpath: str) -> str | None:
    """The rule that produces `artifact_relpath` (module-relative canonical path), or None."""
    for rule in RULES.values():
        for glob in _canonical_output_globs(rule):
            if fnmatch.fnmatch(artifact_relpath, glob):
                return rule.name
    return None


def input_producers(rule_name: str) -> set[str]:
    """Producing rules of every input-selector glob of `rule_name` (excluding self)."""
    rule = RULES[rule_name]
    out: set[str] = set()
    for globs in rule.inputs.values():
        for g in globs:
            p = producer_of(g)
            if p is not None and p != rule_name:
                out.add(p)
    return out


def sort_prereqs(rule_name: str) -> set[str]:
    """排序前驱(R) = {producers of R's inputs} ∪ ADVISORY_ORDER[R], minus R itself.
    ORDERING-ONLY: consumed exclusively by delivery's no-overtake gate. Freshness and
    proof validity use input_producers/input_closure (artifact edges), never this."""
    return input_producers(rule_name) | set(ADVISORY_ORDER.get(rule_name, ()))


def input_closure(rule_name: str) -> set[str]:
    """TRANSITIVE closure of artifact-edge producers (§3.4 输入闭包). Excludes
    ADVISORY_ORDER by construction. Consumed by failure-freshness (schedule) and by
    fix_owner legality (kernel diagnose: fix_owner must produce an artifact inside the
    failed proof's input closure)."""
    seen: set[str] = set()
    frontier = input_producers(rule_name)
    while frontier:
        nxt: set[str] = set()
        for p in frontier:
            if p not in seen:
                seen.add(p)
                nxt |= input_producers(p)
        frontier = nxt
    return seen


def workdir_root(rule_name: str) -> tuple[str, ...]:
    return RULES[rule_name].workdir_root
