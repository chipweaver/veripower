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
    proof: str | None = None
    oracle: tuple[str, str] | None = None  # (ref, grade)
    oracle_selector: str | None = (
        None  # proposed-oracle content selector (workdir-root-relative glob)
    )
    params: tuple[str, ...] = ()
    carry: tuple[
        str, ...
    ] = ()  # self-products to copy into a fresh workdir (self-carry)
    no_carry: tuple[
        str, ...
    ] = ()  # globs excluded from carry (per-round review records)


RULES: dict[str, Rule] = {
    "specification": Rule(
        name="specification",
        stage="specification",
        skill="veripower:specification",
        execution="main-thread",
        workdir_root=("Design", "specification"),
        inputs={"brainstorm": ("brainstorm.md",)},
        outputs=(
            "design.md",
            "*.md",  # *.md = the per-child <child>.md docs (N>=1) — real
            # promoted products; sim-plan/rtl-design consume them as inputs
            "manifest.json",
            "ppa.json",
            "clocks.json",
            "features.json",
            "check-hints/*.json",
            "top-io.json",
            "interconnects.json",
            "spec-review/*.md",
            "constraints/*.sdc",
            "constraints/*.sgdc",
        ),
        proof="specification",
        oracle=("spec-review", "proposed"),
        oracle_selector="spec-review/*.md",
        carry=("**",),
        no_carry=("spec-review/*.md",),
    ),
    "simulation-plan": Rule(
        name="simulation-plan",
        stage="simulation-plan",
        skill="veripower:simulation-plan",
        execution="main-thread",
        workdir_root=("Verification", "simulation-plan"),
        inputs={
            "design": ("Design/specification/design.md",),
            "manifest": ("Design/specification/manifest.json",),
            "children": ("Design/specification/*.md",),
            "clocks": ("Design/specification/clocks.json",),
            "features": ("Design/specification/features.json",),
            "check_hints": ("Design/specification/check-hints/*.json",),
            "top_io": ("Design/specification/top-io.json",),
            # NOT interconnects.json: cross-child wires are internal to the DUT, so no
            # plan field derives from them, and binding it would let a wire-only edit
            # invalidate the plan and its review.
        },
        outputs=(
            "verification-plan.md",
            "tb-scaffold.json",
            "sequences.json",
            "power-scenarios.json",
            "plan-review/*.md",  # review.md + the user's decisions.md
        ),
        proof="simulation-plan",
        oracle=("plan-review", "proposed"),
        oracle_selector="plan-review/*.md",
        carry=("**",),
        no_carry=("plan-review/*.md",),
    ),
    "rtl-design": Rule(
        name="rtl-design",
        stage="rtl-design",
        skill="veripower:rtl-design",
        execution="main-thread",
        workdir_root=("Design", "rtl-design"),
        inputs={
            "design": ("Design/specification/design.md",),
            "manifest": ("Design/specification/manifest.json",),
            "children": ("Design/specification/*.md",),
            # Read by the child sub-Tasks (create_generated_clock, set_case_analysis and
            # quasi_static annotations per references/child-task-contract.md), not by any
            # script in this stage.
            "clocks": ("Design/specification/clocks.json",),
            "top_io": ("Design/specification/top-io.json",),
            "interconnects": ("Design/specification/interconnects.json",),
        },
        outputs=(
            "*.v",
            "rtl-files.json",
            "constraint-annotations.json",
            "semantic-review/*.md",
        ),
        proof="rtl-design",
        oracle=("semantic-review", "proposed"),
        oracle_selector="semantic-review/*.md",
        carry=("**",),
        no_carry=("semantic-review/*.md",),
    ),
    "lint-cdc": Rule(
        name="lint-cdc",
        stage="lint-cdc",
        skill="veripower:lint-cdc",
        execution="task",
        workdir_root=("Design", "lint-cdc"),
        inputs={
            "rtl": ("Design/rtl-design/*.v", "Design/rtl-design/rtl-files.json"),
            # The per-child SGDC/SDC annotations the agent transcribes into the
            # constraint scripts, in the child's real module names.
            "annotations": ("Design/rtl-design/constraint-annotations.json",),
            "sgdc_seed": ("Design/specification/constraints/*.sgdc",),
            # TOP comes from manifest.module. The specification stage root is already
            # reachable through the constraints key, but only the declared globs are
            # fingerprinted — without this edge a module rename would not invalidate.
            "manifest": ("Design/specification/manifest.json",),
        },
        outputs=(
            "lint-report.txt",
            "cdc-report.txt",
            "lint-violations.json",
            "cdc-violations.json",
            "scripts/constraints.sgdc",
            "scripts/waiver.tcl",
        ),
        proof="lint-cdc",
        oracle=("spyglass-ruleset", "tool"),
        carry=("scripts/waiver.tcl", "scripts/constraints.sgdc"),
    ),
    "synthesis": Rule(
        name="synthesis",
        stage="synthesis",
        skill="veripower:synthesis",
        execution="task",
        workdir_root=("Design", "synthesis"),
        inputs={
            "rtl": ("Design/rtl-design/*.v", "Design/rtl-design/rtl-files.json"),
            # The per-child SGDC/SDC annotations the agent transcribes into the
            # constraint scripts, in the child's real module names.
            "annotations": ("Design/rtl-design/constraint-annotations.json",),
            "sdc": ("Design/specification/constraints/*.sdc",),
            # TOP comes from manifest.module. The specification stage root is already
            # reachable through the constraints key, but only the declared globs are
            # fingerprinted — without this edge a module rename would not invalidate.
            "manifest": ("Design/specification/manifest.json",),
            "ppa": ("Design/specification/ppa.json",),
        },
        outputs=(
            "out/*_syn.v",
            "out/*_syn.sdc",
            "out/*_syn.sdf",
            "reports/qor.rpt",
            "constraints.sdc",
        ),
        proof="synthesis",
        oracle=("dc-shell", "tool"),
        carry=("constraints.sdc",),  # the timing exceptions the agent supplements
    ),
    "timing-analysis": Rule(
        name="timing-analysis",
        stage="timing-analysis",
        skill="veripower:timing-analysis",
        execution="task",
        workdir_root=("Design", "timing-analysis"),
        inputs={
            # One key, because both resolve to the same producer stage root and the
            # run reads them as a pair: PT links the netlist and constrains it with
            # the SDC synthesis exported beside it.
            "netlist": (
                "Design/synthesis/out/*_syn.v",
                "Design/synthesis/out/*_syn.sdc",
            ),
        },
        outputs=("timing-report.txt",),
        proof="timing-analysis",
        oracle=("pt-shell", "tool"),
    ),
    "simulation": Rule(
        name="simulation",
        stage="simulation",
        skill="veripower:simulation",
        execution="main-thread",
        workdir_root=("Verification", "simulation"),
        inputs={
            "rtl": ("Design/rtl-design/*.v", "Design/rtl-design/rtl-files.json"),
            # NOT constraint-annotations.json: simulation consumes only the file layout,
            # so binding it would let an annotation-only edit falsely invalidate (D6/G4).
            "plan": ("Verification/simulation-plan/verification-plan.md",),
            # NOT power-scenarios.json: simulation builds no power test, so binding it
            # would let a scenario-only edit falsely invalidate a full compile + regress.
            "scaffold": (
                "Verification/simulation-plan/tb-scaffold.json",
                "Verification/simulation-plan/sequences.json",
            ),
        },
        outputs=(
            "case-results-summary.md",
            "conformance-review.md",
            "env.sh",
            "filelist.f",
            "rtl_filelist.f",
            "tb/uvm/*",
        ),  # TB env: real
        # promoted products (sim/result.py enumerate_artifacts) — power-analysis consumes them
        proof="simulation",
        oracle=("tb-refmodel", "proposed"),
        oracle_selector="tb/uvm/refmodel/*",  # pin endorses the JUDGE itself (spec §2) —
        # survives runs; content drift (LLM regenerates refmodel) drops the pin at reap
        carry=("**",),
        no_carry=("conformance-review.md",),
    ),
    "power-analysis": Rule(
        name="power-analysis",
        stage="power-analysis",
        skill="veripower:power-analysis",
        execution="task",
        workdir_root=("Verification", "power-analysis"),
        inputs={
            "netlist": (
                "Design/synthesis/out/*_syn.v",
                "Design/synthesis/out/*_syn.sdc",
                "Design/synthesis/out/*_syn.sdf",
            ),
            "tb_env": (
                "Verification/simulation/env.sh",
                "Verification/simulation/filelist.f",
                "Verification/simulation/rtl_filelist.f",
                "Verification/simulation/tb/uvm/*",
            ),
            # sequences.json for the sequence_ref -> agent resolution, and the scenarios
            # themselves; NOT tb-scaffold.json, whose testpoints/agents this stage never reads.
            "scaffold": (
                "Verification/simulation-plan/sequences.json",
                "Verification/simulation-plan/power-scenarios.json",
            ),
            "ppa": ("Design/specification/ppa.json",),
        },
        outputs=("reports_ptpx/*/power_hier.rpt",),
        proof="power-analysis",
        oracle=("pt-shell", "tool"),
    ),
    "simulation-triage": Rule(
        name="simulation-triage",
        stage="simulation-triage",
        skill="veripower:simulation-triage",
        execution="task",
        workdir_root=("Verification", "simulation-triage"),
        inputs={
            "design": ("Design/specification/design.md",),
            "rtl": ("Design/rtl-design/*.v", "Design/rtl-design/rtl-files.json"),
            "plan": ("Verification/simulation-plan/verification-plan.md",),
        },
        outputs=(),
        proof=None,
        oracle=None,
        params=("sim_run",),
    ),
}

FORWARD_PRIORITY: list[str] = [
    "specification",
    "simulation-plan",
    "rtl-design",
    "lint-cdc",
    "synthesis",
    "timing-analysis",
    "simulation",
    "power-analysis",
]

PIPELINE_INPUTS: tuple[str, ...] = ("brainstorm.md",)

# Sequencing edges that are NOT data dependencies: synthesis does not consume lint's
# reports, but a lint failure changes the RTL under it, so letting the cheap detector speak
# first avoids spending the expensive stage on a round that is about to be redone. Read by
# exactly one place — schedule._held_by_advisory — and never by freshness, input
# availability, or failure attribution, which are artifact edges only.
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
