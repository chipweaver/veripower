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
    # Excluded: brainstorm (pre-pipeline, own session) and design-flow (the
    # Orchestrator skill — it drives the kernel, it is not a scheduled rule).
    NON_RULE_SKILLS = {"brainstorm", "design-flow"}
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


def test_sort_prereqs_examples():
    # rtl-design not blocked by simulation-plan (no artifact edge, no advisory edge).
    assert "simulation-plan" not in rules.sort_prereqs("rtl-design")
    # synthesis blocked by lint-cdc via advisory edge.
    assert "lint-cdc" in rules.sort_prereqs("synthesis")
    # power-analysis blocked by timing-analysis via advisory edge.
    assert "timing-analysis" in rules.sort_prereqs("power-analysis")


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


def test_simulation_does_not_bind_rtl_readme():
    # D6/G4: simulation reads top from manifest.module (spec §4.3), not README prose; README
    # is not a sim verdict-dependency, so it must NOT be a declared simulation input (binding
    # it made README-only edits falsely invalidate the simulation proof). lint-cdc / synthesis
    # DO legitimately bind README (SGDC/SDC annotation notes).
    sim_globs = [g for gs in rules.RULES["simulation"].inputs.values() for g in gs]
    assert "Design/rtl-design/README.md" not in sim_globs
    for r in ("lint-cdc", "synthesis"):
        globs = [g for gs in rules.RULES[r].inputs.values() for g in gs]
        assert "Design/rtl-design/README.md" in globs, f"{r} should still bind README"
