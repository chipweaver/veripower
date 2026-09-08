"""VeriPower rule registry — the single SSoT for what the kernel schedules.

One Rule = one kernel-scheduled unit. Artifact-level input/output selectors are
module-relative canonical-path globs. The dependency graph is DERIVED from these
(producer_of): no separate stage-view DAG is maintained. Dependency-light leaf —
import the bare way (`import rules`)."""

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
    oracle: tuple[str, str] | None = None  # (ref, grade)
    oracle_selector: str | None = (
        None  # proposed-oracle content selector (workdir-root-relative glob)
    )
    params: tuple[str, ...] = ()
    # The diagnostic to dispatch when THIS rule fails and names nobody. A rule name rather
    # than a scheduler branch: which stage has an analyzer behind it is a registry fact, and
    # the one place that used to know it (`schedule._disposition`) carried the only rule-name
    # literal in the scheduler.
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
        oracle=("spec-review", "proposed"),
        oracle_selector="spec-review",
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
            "children": ("Design/specification/children",),
            "clocks": ("Design/specification/clocks.json",),
            "requirements": ("Design/specification/requirements.json",),
            "check_hints": ("Design/specification/check-hints.json",),
            "top_io": ("Design/specification/top-io.json",),
            # NOT interconnects.json: cross-child wires are internal to the DUT, so no
            # plan field derives from them, and binding it would let a wire-only edit
            # invalidate the plan and its review.
        },
        proof="simulation-plan",
        oracle=("plan-review", "proposed"),
        oracle_selector="plan-review",
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
            "children": ("Design/specification/children",),
            # Read by the child sub-Tasks (create_generated_clock, set_case_analysis and
            # quasi_static annotations), not by any
            # script in this stage.
            "clocks": ("Design/specification/clocks.json",),
            "top_io": ("Design/specification/top-io.json",),
            "interconnects": ("Design/specification/interconnects.json",),
            # The engineer's requirements, one row each with the judge that establishes it.
            # The child authors read the rows that bear on their RTL; the intent reviewers
            # read the rows judged by this stage.
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="rtl-design",
        oracle=("semantic-review", "proposed"),
        oracle_selector="semantic-review",
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
            # TOP comes from manifest.module. The specification stage root is already
            # reachable through the constraints key, but only the declared globs are
            # fingerprinted — without this edge a module rename would not invalidate.
            "manifest": ("Design/specification/manifest.json",),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="lint-cdc",
        oracle=("spyglass-ruleset", "tool"),
        carry=("scripts/waiver.tcl", "scripts/local.sgdc"),
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
            # TOP comes from manifest.module. The specification stage root is already
            # reachable through the constraints key, but only the declared globs are
            # fingerprinted — without this edge a module rename would not invalidate.
            "manifest": ("Design/specification/manifest.json",),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="synthesis",
        oracle=("dc-shell", "tool"),
        carry=("constraints.local.sdc",),  # the timing exceptions the agent supplements
    ),
    "timing-analysis": Rule(
        name="timing-analysis",
        skill="veripower:timing-analysis",
        execution="task",
        workdir_root=("Design", "timing-analysis"),
        inputs={
            "intent": ("intent",),
            # One key, because both resolve to the same producer stage root and the
            # run reads them as a pair: PT links the netlist and constrains it with
            # the SDC synthesis exported beside it.
            "netlist": ("Design/synthesis/out",),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="timing-analysis",
        oracle=("pt-shell", "tool"),
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
        oracle=("tb-refmodel", "proposed"),
        oracle_selector="tb/uvm/refmodel",  # pin endorses the JUDGE itself —
        # survives runs; content drift (LLM regenerates refmodel) drops the pin at reap
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
            "tb_env": (
                "Verification/simulation/env.sh",
                "Verification/simulation/filelist.f",
                "Verification/simulation/rtl_filelist.f",
                "Verification/simulation/tb/uvm",
            ),
            # sequences.json for the sequence_ref -> agent resolution, and the scenarios
            # themselves; NOT tb-scaffold.json, whose testpoints/agents this stage never reads.
            "scaffold": (
                "Verification/simulation-plan/sequences.json",
                "Verification/simulation-plan/power-scenarios.json",
            ),
            "requirements": ("Design/specification/requirements.json",),
        },
        proof="power-analysis",
        oracle=("pt-shell", "tool"),
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
            # The failed run itself — the waveform kept at its run-dir root, the failing
            # case list, the logs. Declaring what it already reads is what puts simulation
            # in this rule's input closure, so the antichain holds the regression back
            # while the analysis is open instead of spending it on the run being analysed.
            # Availability is unaffected: a rule with no proof is always dispatchable.
            "sim": ("Verification/simulation/case-results-summary.md",),
            "requirements": ("Design/specification/requirements.json",),
        },
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

# The intent tree: the engineer's container at the module root, holding the intent document
# and whatever they delivered with it that the document names as authoritative (a reference
# model, a register map, a standard). It has no producer — a human puts it there — so every
# rule binds it as a PIPELINE_INPUT, whose key resolves to the container itself and whose
# version is one merkle over all of it. A row pointing at a file inside is read there by
# whoever judges it.
PIPELINE_INPUTS: tuple[str, ...] = ("intent",)

# The entry document inside the container. `input_available` requires THIS rather than the
# container, so an empty intent/ blocks at the kernel instead of dispatching a stage that
# would find no document and land blocked.
INTENT_DOC: str = "intent/brainstorm.md"

# Sequencing edges that are NOT data dependencies: synthesis does not consume lint's
# reports, but a lint failure changes the RTL under it, so letting the cheap detector speak
# first avoids spending the expensive stage on a round that is about to be redone. Read by
# exactly one place — schedule._held_by_advisory — and never by freshness, input
# availability, or failure attribution, which are artifact edges only.
ADVISORY_ORDER: dict[str, tuple[str, ...]] = {
    "synthesis": ("lint-cdc",),
    "power-analysis": ("timing-analysis",),
}


def producer_of(artifact_relpath: str) -> str | None:
    """The rule that produces `artifact_relpath` (module-relative canonical path), or None.

    The stage root that contains the path IS the producer — workdir_roots are disjoint, so
    this is exact. It replaces a match against declared output globs, which could only ever
    be a lower bound on what a stage actually promotes (kernel._fingerprint_outputs records
    the real set)."""
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
    """TRANSITIVE closure of artifact-edge producers (输入闭包). Excludes
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
