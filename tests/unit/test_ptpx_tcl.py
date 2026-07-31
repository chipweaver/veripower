"""Structural invariants of the deployed templates/scripts/ptpx.tcl.

PT is not in CI, so nothing here executes the script. These assertions exist for
the properties whose loss is silent: a batch that reports the wrong number, or a
report the flow stops producing. Each one was established by running the script
against a real 143k-cell netlist; the comment on each says what was measured.
"""

import re
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


def test_the_annotation_gate_reads_the_report_it_promotes(src: str) -> None:
    # The gate used to redirect report_switching_activity into its own
    # switching_not_annotated.rpt and the loop redirect it again into
    # switching_activity.rpt. On a real run the two differed only in their Date line —
    # read_saif fixes the annotation, so the table is the same before and after
    # update_power — and the second name was one more filename to keep in sync under a
    # label ("not annotated") that described neither file.
    assert "switching_not_annotated" not in src
    assert src.count("report_switching_activity") == 1, (
        "the switching report is written once, and the gate reads that file"
    )
    # The one write goes to the promoted name, and the gate reads back that same path.
    assert re.search(
        r'set\s+_act_rpt\s+\[file join \$reports_dir "switching_activity\.rpt"\]', src
    ), "the gate's report path is no longer the promoted switching_activity.rpt"
    assert re.search(r"redirect -file \$_act_rpt \{report_switching_activity\}", src)
    assert re.search(r"open \$_act_rpt r", src), "the gate must read back what it wrote"


def test_the_gate_keeps_one_way_to_read_the_annotation_percentage(src: str) -> None:
    # PT M-2016.12 prints the per-object-type table and no "Annotated cell percentage"
    # line, which the code's own comment recorded while keeping a branch for it. A second
    # regex that no observed report can match is a branch nobody can reach.
    assert "Annotated" not in src, "the unreachable percentage-line branch is back"
    assert src.count("regexp -line") == 1
