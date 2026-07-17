from pathlib import Path

RTL = Path("skills/rtl-design/SKILL.md").read_text()


def test_rtl_44_has_selfconverge_for_rtl_locus():
    # rtl-locus 走 self-converge（不再 "no in-skill autofix"）
    assert "self-converge" in RTL
    assert "no in-skill autofix" not in RTL


def test_rtl_44_spec_locus_still_fails_out():
    # spec-locus 仍 fail-out（走上游路由，不 stage 内硬修）
    assert "loci.spec" in RTL and "fail-out" in RTL
