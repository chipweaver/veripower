# tests/unit/test_infra_coverage_wiring.py
"""Infra wires urg text report + parse_coverage at the regress tail."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "skills/simulation/templates/infra/Makefile"
REGRESS = ROOT / "skills/simulation/templates/infra/scripts/run_vcs_regression.sh"


def test_makefile_has_text_coverage_target():
    mk = MAKEFILE.read_text()
    assert "-report cov_merge -format text" in mk
    assert "parse_coverage.py" in mk
    assert "structural-coverage.json" in mk


def test_regress_invokes_coverage_step():
    sh = REGRESS.read_text()
    # coverage must be wired on the regress arm specifically (within regress) ... ;;)
    assert re.search(r"regress\)(?:(?!;;).)*make coverage", sh, re.DOTALL), (
        "make coverage must be in the regress) arm"
    )


def test_smoke_arm_does_not_run_coverage():
    sh = REGRESS.read_text()
    smoke_arm = re.search(r"smoke\)(.*?);;", sh, re.DOTALL)
    assert smoke_arm is not None, "smoke) arm not found"
    assert "make coverage" not in smoke_arm.group(1)
