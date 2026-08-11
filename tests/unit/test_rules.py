import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import rules  # noqa: E402

SKILLS_DIR = ROOT / "skills"


def test_nine_rules_eight_stages_plus_triage():
    assert len(rules.RULES) == 9
    # FORWARD_PRIORITY doubles as the signoff obligation set (_STAGE_PROOFS /
    # facts.signoff_gate, which iterates it whole), so anchor it to the SEMANTIC property —
    # proof-producing rules — not a hardcoded name exclusion. A future proof-rule added to
    # RULES but not FORWARD_PRIORITY would otherwise be silently exempt from the gate (F-5).
    assert set(rules.FORWARD_PRIORITY) == {
        n for n, r in rules.RULES.items() if r.proof is not None
    }
    assert "simulation-triage" in rules.RULES
    assert rules.RULES["simulation-triage"].proof is None


def test_skill_dir_rule_bidirectional_coverage():
    # 缝五 measurable anchor: every stage skill dir <-> a rule, both directions.
    # Excluded: brainstorm and setup (pre-pipeline, own session) and design-flow
    # (the Orchestrator skill — it drives the kernel, it is not a scheduled rule).
    NON_RULE_SKILLS = {"brainstorm", "setup", "design-flow"}
    skill_dirs = {
        p.name
        for p in SKILLS_DIR.iterdir()
        if (p / "SKILL.md").exists() and p.name not in NON_RULE_SKILLS
    }
    rule_skills = {r.skill.split(":", 1)[1] for r in rules.RULES.values()}
    assert skill_dirs == rule_skills


def test_every_input_traces_to_a_producer_or_pipeline_input():
    for name, rule in rules.RULES.items():
        for globs in rule.inputs.values():
            for g in globs:
                if g in rules.PIPELINE_INPUTS:
                    continue
                assert rules.producer_of(g) is not None, (
                    f"{name}: input {g} has no producer"
                )


def test_declared_input_graph_is_acyclic_self_edges_excluded():
    # input_producers drops self-edges (in∩out inputs), so the derived graph is acyclic.
    graph = {n: rules.input_producers(n) for n in rules.RULES}
    _assert_acyclic(graph)


def test_advisory_edges_reference_registered_rules_and_stay_acyclic():
    for consumer, prereqs in rules.ADVISORY_ORDER.items():
        assert consumer in rules.RULES
        for p in prereqs:
            assert p in rules.RULES
    graph = {
        n: rules.input_producers(n) | set(rules.ADVISORY_ORDER.get(n, ()))
        for n in rules.RULES
    }
    _assert_acyclic(graph)


def test_proposed_oracle_declares_selector_within_inputs_union_outputs():
    # spec §1.3 condition-3 structural premise: a proposed oracle's content selector
    # is covered by that rule's inputs ∪ outputs. The selector lives on the Rule
    # itself (oracle_selector); tool-grade oracles carry none.
    import fnmatch

    for rule in rules.RULES.values():
        if rule.oracle and rule.oracle[1] == "proposed":
            sel = rule.oracle_selector
            assert sel, f"{rule.name}: proposed oracle without oracle_selector"
            sel_base = sel.rstrip("/*")  # dir-glob selector matches via its base path
            covered = any(
                o == sel
                or fnmatch.fnmatch(sel_base, o.rstrip("/*"))
                or fnmatch.fnmatch(sel_base, o)
                for o in rule.outputs
            ) or any(g.endswith(sel) for globs in rule.inputs.values() for g in globs)
            assert covered, f"{rule.name}: oracle_selector {sel} not in inputs∪outputs"
        elif rule.oracle:
            assert rule.oracle_selector is None, (
                f"{rule.name}: tool oracle must not carry a selector"
            )


def test_advisory_edges_are_sequencing_only():
    """ADVISORY_ORDER holds the two edges that are NOT data dependencies, and holds only
    those. A rule with no advisory entry can never be held back by the no-overtake gate,
    and an advisory predecessor must not also be an input producer — otherwise the gate
    would duplicate a constraint rule_available already enforces."""
    assert rules.ADVISORY_ORDER == {
        "synthesis": ("lint-cdc",),
        "power-analysis": ("timing-analysis",),
    }
    for consumer, prereqs in rules.ADVISORY_ORDER.items():
        producers = rules.input_producers(consumer)
        for p in prereqs:
            assert p not in producers, (
                f"{consumer}: {p} is an input producer, so the advisory edge is redundant"
            )
    # rtl-design is held back by nothing: simulation-plan is neither producer nor advisory.
    assert "rtl-design" not in rules.ADVISORY_ORDER
    assert "simulation-plan" not in rules.input_producers("rtl-design")


def _assert_acyclic(graph):
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(graph, WHITE)

    def visit(n):
        color[n] = GREY
        for m in graph.get(n, ()):
            if color[m] == GREY:
                pytest.fail(f"cycle through {n}->{m}")
            if color[m] == WHITE:
                visit(m)
        color[n] = BLACK

    for n in graph:
        if color[n] == WHITE:
            visit(n)


def test_simulation_does_not_bind_constraint_annotations():
    # D6/G4: simulation consumes only the RTL file layout, so binding the annotations would
    # let an annotation-only edit falsely invalidate the simulation proof. lint-cdc and
    # synthesis DO bind them — their agents transcribe them into the constraint scripts.
    ann = "Design/rtl-design/constraint-annotations.json"
    sim_globs = [g for gs in rules.RULES["simulation"].inputs.values() for g in gs]
    assert ann not in sim_globs
    for r in ("lint-cdc", "synthesis"):
        globs = [g for gs in rules.RULES[r].inputs.values() for g in gs]
        assert ann in globs, f"{r} should bind the constraint annotations"


def test_carry_no_carry_fields_and_values():
    import rules

    # authors carry everything, drop their review record
    assert rules.RULES["specification"].carry == ("**",)
    assert rules.RULES["specification"].no_carry == ("spec-review/*.md",)
    assert rules.RULES["simulation-plan"].carry == ("**",)
    assert rules.RULES["simulation-plan"].no_carry == ("plan-review/*.md",)
    assert rules.RULES["rtl-design"].carry == ("**",)
    assert rules.RULES["rtl-design"].no_carry == ("semantic-review/*.md",)
    assert rules.RULES["simulation"].carry == ("**",)
    assert rules.RULES["simulation"].no_carry == ("conformance-review.md",)
    # Both constraint stages carry ONLY what they author. The file the tool reads is
    # assembled from the upstream seed every round, so carrying it would pin the seed to
    # whatever it said the round the workdir was first created.
    assert rules.RULES["lint-cdc"].carry == (
        "scripts/waiver.tcl",
        "scripts/local.sgdc",
    )
    assert rules.RULES["lint-cdc"].no_carry == ()
    assert rules.RULES["synthesis"].carry == ("constraints.local.sdc",)
    assert rules.RULES["synthesis"].no_carry == ()
    # pure transformers + triage carry nothing
    for r in ("timing-analysis", "power-analysis", "simulation-triage"):
        assert rules.RULES[r].carry == ()
        assert rules.RULES[r].no_carry == ()
    # frozen dataclass still rejects mutation
    assert getattr(rules.Rule, "__dataclass_params__").frozen


def test_triage_has_upstream_inputs_and_no_proof():
    import rules

    r = rules.RULES["simulation-triage"]
    assert r.proof is None
    assert set(r.inputs) >= {"design", "rtl", "plan"}
