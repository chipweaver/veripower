"""dc_run.tcl must gate elaborate and link on their return values.

Why the return value and not a cell-attribute query: DC classifies an unresolved
reference as a Warning, not an Error, so dc_run.tcl's `check_design` gate (which
aborts only on a `^Error:` line) does not fire on it, and `compile` then succeeds on
the reduced design. The netlist that comes out is missing a whole module yet reports
a perfectly clean QoR — and a *smaller* one, so an area-ceiling PPA target cannot
catch it either. `analyze` / `elaborate` / `link` each return 0 on failure and 1 on
success, the same contract the `compile` gate already relies on, and that return
value is the only reliable signal here: the `is_unresolved` cell attribute matches
nothing in this case, and `is_black_box` matches every inferred DesignWare cell, so
neither is usable as a gate.

Note that the gate does not depend on any of that being true in a given DC release:
gating the return value is correct whether or not check_design would also have
caught the case. The analyze side is generated, so it is locked from the generator
in tests/unit/test_synthesis_bootstrap.py::test_rtl_load_gates_every_analyze.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DC_RUN = ROOT / "skills/synthesis/templates/scripts/dc_run.tcl"


def test_elaborate_is_gated():
    assert re.search(r"if \{!\[elaborate ", DC_RUN.read_text())


def test_link_is_gated():
    assert re.search(r"if \{!\[link\]\}", DC_RUN.read_text())


def test_no_ungated_elaborate_or_link_call():
    lines = [ln.strip() for ln in DC_RUN.read_text().splitlines()]
    assert "link" not in lines
    assert not [ln for ln in lines if re.fullmatch(r"elaborate \$?\w+", ln)]
