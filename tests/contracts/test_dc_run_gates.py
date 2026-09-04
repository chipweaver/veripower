"""dc_run.tcl must gate elaborate and link on their return values.

Why the return value and not a cell-attribute query: DC classifies an unresolved
reference as a Warning, not an Error, so dc_run.tcl's `check_design` gate (which
aborts only on a `^Error:` line) does not fire on it, and `compile_ultra` then succeeds
on the reduced design. The netlist that comes out is missing a whole module yet reports
a perfectly clean QoR — and a *smaller* one, so an area-ceiling PPA target cannot
catch it either. `analyze` / `elaborate` / `link` each return 0 on failure and 1 on
success, the same contract the `compile_ultra` gate already relies on, and that return
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


def test_mapping_is_compile_ultra_and_is_gated():
    """The mapping command is compile_ultra, gated on its return value.

    The area and slack bounds are judged against DC-Ultra QoR, so a silent plain-compile path
    would grade a different design than the one the targets describe. A missing DC-Ultra
    checkout is env-precheck's to report, not this script's to work around.
    """
    code = [
        ln.strip()
        for ln in DC_RUN.read_text().splitlines()
        if not ln.strip().startswith("#")
    ]
    assert [ln for ln in code if re.search(r"if \{!\[compile_ultra\]\}", ln)]
    assert not [ln for ln in code if re.search(r"(?<!_)\bcompile\b(?!_)", ln)]


def test_wire_load_is_selected_and_verified():
    """The interconnect estimate is chosen here or nowhere, and the choice is verified.

    A library carries several wire load models and typically declares neither a default nor a
    selection group (checked on TSMC 90 and SMIC 180: five models each, zero
    `default_wire_load` / `wire_load_selection` keys), so nothing selects one unless dc_run
    does. With none selected DC reports `Net Interconnect area: undefined` and no net
    capacitance, and PT-PX — which reads the SDC written here — then reports zero net
    switching power. Measured on a real block with one activity assumption: selecting the
    library's smallest model raised net switching power 6.2x and total power 24%.

    The verification cannot use the command's return value or the design attribute:
    `set_wire_load_model` returns success for a name the library does not have (printing
    `Error: Wire load ... not found` without raising), and the attribute is unset in both the
    accepted and the rejected case. The area report is the signal that distinguishes them.
    """
    code = DC_RUN.read_text()
    assert re.search(r"set_wire_load_model -name \$wlm", code)
    assert re.search(r"WIRE_LOAD_MODEL", code)
    # the post-set verification, anchored on the regexp rather than the comment above it
    # that quotes the same report line
    m = re.search(r"regexp \{No wire load specified\}", code)
    assert m
    assert re.search(r"exit 1", code[m.end() : m.end() + 300])
