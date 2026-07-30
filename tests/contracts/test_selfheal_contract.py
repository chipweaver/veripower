from pathlib import Path

RTL = Path("skills/rtl-design/SKILL.md").read_text()


# Anchored on the two machine keys the branch reads, not on the prose naming it: the
# invariant is where each locus gets repaired, and `loci.rtl` / `loci.spec` are what
# validate-review actually emits, so they survive a rewording that keeps the behaviour.
def test_rtl_rtl_locus_is_repaired_in_stage():
    # rtl-locus 缺陷在本阶段重派修复（不再 "no in-skill autofix"）
    assert "`loci.rtl`" in RTL and "re-dispatch" in RTL
    assert "no in-skill autofix" not in RTL


def test_rtl_spec_locus_is_handed_upstream():
    # spec-locus 不在阶段内硬修，交回上游 fix owner
    assert "`loci.spec`" in RTL and "--fix-owner" in RTL


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
