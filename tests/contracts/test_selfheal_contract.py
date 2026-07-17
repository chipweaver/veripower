from pathlib import Path

RTL = Path("skills/rtl-design/SKILL.md").read_text()


def test_rtl_44_has_selfconverge_for_rtl_locus():
    # rtl-locus 走 self-converge（不再 "no in-skill autofix"）
    assert "self-converge" in RTL
    assert "no in-skill autofix" not in RTL


def test_rtl_44_spec_locus_still_fails_out():
    # spec-locus 仍 fail-out（走上游路由，不 stage 内硬修）
    assert "loci.spec" in RTL and "fail-out" in RTL


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
