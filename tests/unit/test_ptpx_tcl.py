"""Structural invariants of the deployed templates/scripts/ptpx.tcl.

PT is not in CI, so nothing here executes the script. These assertions exist for
the properties whose loss is silent: a batch that reports the wrong number, or a
report the flow stops producing. Each one was established by running the script
against a real 143k-cell netlist; the comment on each says what was measured.
"""

from pathlib import Path

import pytest

PTPX = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "power-analysis"
    / "templates"
    / "scripts"
    / "ptpx.tcl"
)


@pytest.fixture(scope="module")
def src() -> str:
    return PTPX.read_text(encoding="utf-8")


def test_a_discarded_warm_up_precedes_the_reporting_loop(src: str) -> None:
    # Whichever scenario runs first in a session reports less power than the identical
    # scenario run second: measured 32.2 mW then 34.2 mW for one peak-activity SAIF, a
    # 6% understatement of the scenario a power target is set against. The warm-up is
    # what makes the reported value independent of SAIF_LIST order, and deleting it
    # brings the understatement back with no other visible symptom.
    warm = src.index("# Warm-up:")
    loop = src.index("# Batch loop over SAIF_LIST")
    assert warm < loop, "the warm-up must run before the first reported scenario"

    warm_block = src[warm:loop]
    assert "update_power" in warm_block, (
        "a warm-up that skips update_power settles nothing"
    )
    # It reports nothing: no report file and no scenario directory come out of it.
    for writes in ("file mkdir", "report_power", "redirect"):
        assert writes not in warm_block, (
            f"the warm-up must not {writes!r} — its numbers are the discarded ones"
        )


def test_the_warm_up_cannot_fail_the_batch(src: str) -> None:
    # Whatever is wrong with the SAIF it picked, the scenario that owns that SAIF
    # reports it below. A warm-up that exits or increments fail_count would turn a
    # single bad scenario into a dead batch.
    warm_block = src[src.index("# Warm-up:") : src.index("# Batch loop over SAIF_LIST")]
    assert "catch {" in warm_block, "the warm-up must swallow its own failures"
    for fatal in ("exit 1", "incr fail_count"):
        assert fatal not in warm_block, f"the warm-up must not {fatal!r}"
