"""Stage declarations and the producer graph derived from their artifact inputs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    name: str
    skill: str
    # A rule that fans out into Level-1 sub-Tasks must be "main-thread": a task
    # subagent may dispatch none.
    execution: str  # "task" | "main-thread"
    workdir_root: tuple[str, ...]
    inputs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    proof: str | None = None
    params: tuple[str, ...] = ()
    # Diagnostic rule used when a failure names no repair owner.
    triage: str | None = None
    carry: tuple[
        str, ...
    ] = ()  # self-products to copy into a fresh workdir (self-carry)
    no_carry: tuple[
        str, ...
    ] = ()  # globs excluded from carry (per-round review records)


RULES: dict[str, Rule] = {
    "specification": Rule(
        name="specification",
        skill="veripower:specification",
        execution="main-thread",
        workdir_root=("Design", "specification"),
        inputs={"intent": ("intent",)},
        proof="specification",
        carry=("**",),
        no_carry=("spec-review/findings/*",),
    ),
    "simulation-plan": Rule(
        name="simulation-plan",
        skill="veripower:simulation-plan",
        execution="main-thread",
        workdir_root=("Verification", "simulation-plan"),
        inputs={
            "intent": ("intent",),
            "design": ("Design/specification/design.md",),
            "manifest": ("Design/specification/manifest.json",),
            "clocks": ("Design/specification/clocks.json",),
            "requirements": ("Design/specification/requirements.json",),
            "check_hints": ("Design/specification/check-hints.json",),
            "top_io": ("Design/specification/top-io.json",),
        },
        proof="simulation-plan",
        carry=("**",),
        no_carry=("plan-review/findings.md",),
    ),
    "rtl-design": Rule(
        name="rtl-design",
        skill="veripower:rtl-design",
        execution="main-thread",
        workdir_root=("Design", "rtl-design"),
        inputs={
            "intent": ("intent",),
            "design": ("Design/specification/design.md",),
            "manifest": ("Design/specification/manifest.json",),
            # Consumed by authors for generated clocks, case analysis and quasi-static annotations.
            "clocks": ("Design/specification/clocks.json",),
            "top_io": ("Design/specification/top-io.json",),
            # Requirement rows name the stage that judges them.
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="rtl-design",
        carry=("**",),
        no_carry=("semantic-review/*",),
    ),
    "lint-cdc": Rule(
        name="lint-cdc",
        skill="veripower:lint-cdc",
        execution="task",
        workdir_root=("Design", "lint-cdc"),
        inputs={
            "intent": ("intent",),
            "rtl": ("Design/rtl-design/src", "Design/rtl-design/rtl-files.json"),
            # The per-child SGDC/SDC annotations the agent transcribes into the
            # constraint scripts, in the child's real module names.
            "annotations": ("Design/rtl-design/constraint-annotations.json",),
            "sgdc_seed": ("Design/specification/constraints/*.sgdc",),
            # Track manifest.module so a module rename invalidates this stage.
            "manifest": ("Design/specification/manifest.json",),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="lint-cdc",
        carry=("**",),
    ),
    "synthesis": Rule(
        name="synthesis",
        skill="veripower:synthesis",
        execution="task",
        workdir_root=("Design", "synthesis"),
        inputs={
            "intent": ("intent",),
            "rtl": ("Design/rtl-design/src", "Design/rtl-design/rtl-files.json"),
            # The per-child SGDC/SDC annotations the agent transcribes into the
            # constraint scripts, in the child's real module names.
            "annotations": ("Design/rtl-design/constraint-annotations.json",),
            "sdc": ("Design/specification/constraints/*.sdc",),
            # Track manifest.module so a module rename invalidates this stage.
            "manifest": ("Design/specification/manifest.json",),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="synthesis",
        carry=("**",),
    ),
    "timing-analysis": Rule(
        name="timing-analysis",
        skill="veripower:timing-analysis",
        execution="task",
        workdir_root=("Design", "timing-analysis"),
        inputs={
            "intent": ("intent",),
            # Consume the complete implementation, including referenced support files.
            "netlist": ("Design/synthesis/out",),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="timing-analysis",
        carry=("**",),
    ),
    "simulation": Rule(
        name="simulation",
        skill="veripower:simulation",
        execution="main-thread",
        workdir_root=("Verification", "simulation"),
        inputs={
            "intent": ("intent",),
            "rtl": ("Design/rtl-design/src", "Design/rtl-design/rtl-files.json"),
            # NOT constraint-annotations.json: simulation consumes only the file layout,
            # so binding it would let an annotation-only edit falsely invalidate.
            "plan": ("Verification/simulation-plan/verification-plan.md",),
            # NOT power-scenarios.json: simulation builds no power test, so binding it
            # would let a scenario-only edit falsely invalidate a full compile + regress.
            "scaffold": (
                "Verification/simulation-plan/tb-scaffold.json",
                "Verification/simulation-plan/sequences.json",
            ),
            # The DUT boundary the TB is built against. Declared rather than copied into the
            # scaffold: a copy can disagree with it, and cannot be checked for totality.
            "spec": (
                "Design/specification/top-io.json",
                "Design/specification/clocks.json",
            ),
            # The requirements the coverage gate reads its thresholds from, and the hints the
            # testpoints cover — read by id, never copied into the scaffold.
            "requirements": ("Design/specification/requirements.json",),
            "check_hints": ("Design/specification/check-hints.json",),
        },
        # promoted products (sim/result.py enumerate_artifacts) — power-analysis consumes them
        proof="simulation",
        triage="simulation-triage",  # the one stage with a deeper analyzer behind it
        carry=("**",),
        no_carry=("check-review.md",),
    ),
    "power-analysis": Rule(
        name="power-analysis",
        skill="veripower:power-analysis",
        execution="task",
        workdir_root=("Verification", "power-analysis"),
        inputs={
            "intent": ("intent",),
            "netlist": ("Design/synthesis/out",),
            "design": ("Design/specification/design.md",),
            "tb_env": (
                "Verification/simulation/tb",
                "Verification/simulation/scripts",
                "Verification/simulation/tests",
                "Verification/simulation/env.sh",
                "Verification/simulation/filelist.f",
            ),
            "plan": (
                "Verification/simulation-plan/verification-plan.md",
                "Verification/simulation-plan/power-scenarios.json",
            ),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="power-analysis",
        carry=("**",),
    ),
    "simulation-triage": Rule(
        name="simulation-triage",
        skill="veripower:simulation-triage",
        execution="task",
        workdir_root=("Verification", "simulation-triage"),
        inputs={
            "intent": ("intent",),
            "design": ("Design/specification/design.md",),
            "rtl": ("Design/rtl-design/src", "Design/rtl-design/rtl-files.json"),
            "plan": ("Verification/simulation-plan/verification-plan.md",),
            # The simulation input orders regression work behind its active diagnosis.
            "sim": ("Verification/simulation/case-results-summary.md",),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof=None,
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

# The engineer-owned intent tree is an external input to every proof.
PIPELINE_INPUTS: tuple[str, ...] = ("intent",)

# Specification requires this document inside the intent tree.
INTENT_DOC: str = "intent/brainstorm.md"

# Advisory ordering applies to scheduled or running predecessors, independently of artifact edges.
ADVISORY_ORDER: dict[str, tuple[str, ...]] = {
    "synthesis": ("lint-cdc",),
    "power-analysis": ("timing-analysis",),
}


def producer_of(artifact_relpath: str) -> str | None:
    """Find the rule whose canonical directory contains the artifact path."""
    parts = tuple(artifact_relpath.split("/"))
    for rule in RULES.values():
        r = rule.workdir_root
        if parts[: len(r)] == r:
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
    """Return transitive artifact producers, excluding advisory ordering edges."""
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


def repair_owners(rule_name: str) -> set[str]:
    """A stage can repair its own work or ask an input producer to repair theirs."""
    return {rule_name} | input_closure(rule_name)


def workdir_root(rule_name: str) -> tuple[str, ...]:
    return RULES[rule_name].workdir_root
