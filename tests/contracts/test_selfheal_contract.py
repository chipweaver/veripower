from pathlib import Path

RTL = Path("skills/rtl-design/SKILL.md").read_text()


# No script reduces the reviews to a verdict any more, so there is no key to anchor on. What
# must survive is the disposition: an RTL defect is repaired here, an intent-source defect is
# named for someone else. Both halves are asserted, so losing either one is a failure.
def test_rtl_defect_is_repaired_in_stage():
    # RTL 缺陷在本阶段重派修复（不再 "no in-skill autofix"）
    assert "re-dispatch" in RTL
    assert "no in-skill autofix" not in RTL


def test_intent_source_defect_is_handed_upstream():
    # design.md / <child>.md 的缺陷不在阶段内硬修，交回上游 fix owner
    assert "intent source" in RTL and "--fix-owner" in RTL


SIM = Path("skills/simulation/SKILL.md").read_text()


def test_sim_conformance_selfheal_no_deferred():
    assert "Self-heal is deferred" not in SIM
    assert "no in-skill fix-loop" not in SIM


def test_sim_conformance_has_selfheal_loop():
    assert "conformance-fix" in SIM
    assert "intent-defect" in SIM and "fail-out" in SIM


def test_conformance_fix_contract_exists():
    assert Path(
        "skills/simulation/references/conformance-fix-task-contract.md"
    ).is_file()
