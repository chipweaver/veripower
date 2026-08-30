"""Both stages that compile the TB must hand gcc the same TB-side flags.

simulation compiles the TB against the RTL; power-analysis compiles the same TB against the
gate netlist. The DUT halves of those command lines legitimately differ — the TB half does not:
the refmodel's include directory and C dialect are properties of the TB, not of the stage
reading it. They cannot be carried in `filelist.f` (VCS ignores `-CFLAGS` inside a `-f` file),
so each command line states them, and this keeps the two statements together. Neither template
carried them until now: the one real run that needed a C reference model hand-edited both
deployed copies, which survived in simulation (Rule.carry brings its scripts forward) and was
erased in power-analysis (no carry — its Makefile is redeployed every round), so that module
could never re-run its power stage.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "skills/simulation/templates/infra/scripts/run_vcs_regression.sh"
PWR = ROOT / "skills/power-analysis/templates/Makefile"

# The TB-side flags, as (regex, human name). The include path is anchored at whatever each
# stage calls the TB root, so only its tail is compared.
TB_FLAGS = [
    # `$$` in the Makefile is Make's escape for a single shell `$`
    (r"-CFLAGS\s+-I\"\$+\{?\w+\}?/tb/uvm/refmodel\"", "refmodel include path"),
    (r"-CFLAGS\s+-std=gnu99", "C dialect"),
    (r"-CFLAGS\s+-DVCS\s+\+vpi", "UVM DPI"),
]


def test_both_tb_compiles_pass_the_same_flags():
    sim, pwr = SIM.read_text(), PWR.read_text()
    for pattern, name in TB_FLAGS:
        assert re.search(pattern, sim), f"simulation's TB compile lost the {name}"
        assert re.search(pattern, pwr), f"power-analysis's TB compile lost the {name}"
