"""Functional simulation supplies the flags required by its own TB template."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "skills/simulation/templates/infra/scripts/run_vcs_regression.sh"

# The TB-side flags, as (regex, human name). The include path is anchored at whatever each
# stage calls the TB root, so only its tail is compared.
TB_FLAGS = [
    # `$$` in the Makefile is Make's escape for a single shell `$`
    (r"-CFLAGS\s+-I\"\$+\{?\w+\}?/tb/uvm/refmodel\"", "refmodel include path"),
    (r"-CFLAGS\s+-std=gnu99", "C dialect"),
    (r"-CFLAGS\s+-DVCS\s+\+vpi", "UVM DPI"),
]


def test_simulation_supplies_its_tb_compile_flags():
    sim = SIM.read_text()
    for pattern, name in TB_FLAGS:
        assert re.search(pattern, sim), f"simulation's TB compile lost the {name}"
