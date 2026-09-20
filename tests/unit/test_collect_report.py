"""Tests for skills/lint-cdc/templates/scripts/collect_report.py (grounded format)."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "lint-cdc" / "templates" / "scripts"))

import collect_report as cr  # noqa: E402


# ── fixtures: faithful real SpyGlass vL-2016.06 moresimple.rpt format ─────────
def hdr(generated, waived, reported, overlimit):
    return (
        "################################################################################\n"
        "#     Report Name      : moresimple\n"
        f"#     Total Number of Generated Messages :        {generated}\n"
        f"#     Number of Waived Messages          :        {waived}\n"
        f"#     Number of Reported Messages        :        {reported}\n"
        f"#     Number of Overlimit Messages       :        {overlimit}\n"
        "################################################################################\n"
        "\nMORESIMPLE REPORT:\n\n"
        "############### Non-BuiltIn -> Goal=lint/lint_rtl ###############\n"
        "ID       Rule              Alias                      Severity        File                       Line    Wt    Message\n"
        "======================================================================================\n"
    )


CLEAN = hdr(0, 0, 0, 0) + "(no reported messages)\n"

# 4 reported rows: Error, SynthesisError, Warning(multi-word alias), Info(empty alias)
MIXED = hdr(4, 0, 4, 0) + (
    "[4F]     STARC05-1.3.1.3   AsyncResetOtherUse         Error           ../../../rtl-design/a.v    171     10    Async reset used as non-reset\n"
    "[2]      SYNTH_133         SYNTH_133                  SynthesisError  ../../../rtl-design/b.v    120     1000  Asynchronous set/reset on data\n"
    "[F8]     Ac_conv04         Control Bus Gray Encoding  Warning         ../../../rtl-design/c.v    90      10    Gray-encoding convergence\n"
    "[34]     W240                                         Info            ../../../rtl-design/d.v    28      10    Input declared but not read\n"
)

# header has no 'Number of Reported Messages' anchor
NO_HEADER = (
    "################################################################################\n"
    "#     Total Number of Generated Messages :        1\n"
    "################################################################################\n"
    "[4F]     R   A   Warning   ../../../rtl-design/a.v   12   10   msg\n"
)

# reported=2 but one bracket row lacks the File/Line/Wt structure -> parse gap
PARSE_GAP = hdr(2, 0, 2, 0) + (
    "[4F]     STARC05   AsyncResetOtherUse   Warning   ../../../rtl-design/a.v   171   10   ok row\n"
    "[XX]     BadRow    truncated line with no numeric columns\n"
)

# a row whose severity token is not error/warning/info
UNKNOWN_SEV = hdr(1, 0, 1, 0) + (
    "[4F]     SomeRule   SomeAlias   Note   ../../../rtl-design/a.v   10   5   unexpected severity\n"
)

# reported says 5 but only 1 bracket row present
COUNT_MISMATCH = hdr(5, 0, 5, 0) + (
    "[4F]     R   A   Warning   ../../../rtl-design/a.v   1   1   m\n"
)

# generated(10) != waived(2) + reported(4)
INTEGRITY = hdr(10, 2, 4, 0) + (
    "[1]   R   A   Warning   ../../../rtl-design/a.v   1   1   m\n"
    "[2]   R   A   Warning   ../../../rtl-design/b.v   2   1   m\n"
    "[3]   R   A   Info      ../../../rtl-design/c.v   3   1   m\n"
    "[4]   R   A   Info      ../../../rtl-design/d.v   4   1   m\n"
)

# overlimit > 0 (other checks pass)
OVERLIMIT = hdr(4, 0, 4, 3) + (
    "[1]   R   A   Warning   ../../../rtl-design/a.v   1   1   m\n"
    "[2]   R   A   Warning   ../../../rtl-design/b.v   2   1   m\n"
    "[3]   R   A   Info      ../../../rtl-design/c.v   3   1   m\n"
    "[4]   R   A   Info      ../../../rtl-design/d.v   4   1   m\n"
)

# two rows colliding on rule:file:line
COLLISION = hdr(2, 0, 2, 0) + (
    "[A1]   W123   AliasX   Warning   ../../../rtl-design/x.v   42   10   net alpha undriven\n"
    "[A2]   W123   AliasX   Warning   ../../../rtl-design/x.v   42   10   net beta undriven\n"
)


def stage(root, body, stage_path="cdc/cdc_verify_struct/spyglass"):
    d = root / "spyglass_work" / stage_path
    d.mkdir(parents=True, exist_ok=True)
    (d / "moresimple.rpt").write_text(body)
    (root / "env.sh").write_text('export TOP="${TOP:-spi_master}"\n')


@pytest.mark.parametrize("duplicates", [False, True])
def test_waived_messages_and_reasons_travel_in_the_existing_report(
    tmp_path, duplicates
):
    stage(tmp_path, hdr(1, 1, 0, 0))
    source = cr.locate("cdc", tmp_path / "spyglass_work")
    row = "[4] W240 Warning work with spaces/core.v 1 10 Input is unused\n"
    waiver = hdr(1, 1, 0, 0) + "Waiver comment : See design rationale.\n" + row
    if duplicates:
        waiver += "Waiver comment : Overlapping waiver.\n" + row
    source.with_name("waiver.rpt").write_text(waiver)
    assert cr.run("cdc", tmp_path) == 0
    assert waiver in (tmp_path / "cdc-report.txt").read_text()
    doc = json.loads((tmp_path / "cdc-violations.json").read_text())
    assert doc["totals"]["waived"] == 1
    assert doc["violations"] == []


@pytest.mark.parametrize("evidence", [None, "truncated", "wrong-count"])
def test_incomplete_waiver_evidence_does_not_publish_a_clean_summary(
    tmp_path, evidence
):
    stage(tmp_path, hdr(1, 1, 0, 0))
    source = cr.locate("cdc", tmp_path / "spyglass_work")
    for name in ("cdc-report.txt", "cdc-violations.json"):
        (tmp_path / name).write_text("old success")
    if evidence is not None:
        body = hdr(1, 1, 0, 0) if evidence == "truncated" else hdr(0, 0, 0, 0)
        source.with_name("waiver.rpt").write_text(body)
    assert cr.run("cdc", tmp_path) != 0
    assert not (tmp_path / "cdc-report.txt").exists()
    assert not (tmp_path / "cdc-violations.json").exists()


def test_zero_waived_messages_do_not_require_a_waiver_report(tmp_path):
    stage(tmp_path, CLEAN)
    assert cr.run("cdc", tmp_path) == 0


# ── parsing units ──────────────────────────────────────────────────────────
def test_parse_header_totals():
    assert cr.parse_header(MIXED) == {
        "generated": 4,
        "waived": 0,
        "reported": 4,
        "overlimit": 0,
    }


def test_parse_header_absent_anchor_returns_none():
    assert cr.parse_header(NO_HEADER) is None


def test_sev_substring_classifies_compound_tokens():
    assert [
        cr.normalize_severity(t)
        for t in ("Fatal", "Error", "SynthesisError", "Warning", "Info")
    ] == ["error", "error", "error", "warning", "info"]
    assert cr.normalize_severity("Note") is None


def test_sev_maps_the_starc_mandatory_token():
    # STARC rules report their policy level in the severity column: a violation of a
    # Mandatory rule reads "Mandatory", not "Error". Left unmapped it returns None and the
    # whole report is rejected as unparseable, which blocks the stage on a clean run.
    assert cr.normalize_severity("Mandatory") == "error"


def test_sev_maps_the_syntax_token_this_stage_exists_to_report():
    # An STX_* row reports "Syntax", which carries none of the substrings above.
    # Unmapped it rejected the whole report as unparseable — on RTL that would not
    # parse, which is the finding this stage most needs to render. Verbatim from a
    # SpyGlass vL-2016.06 lint_rtl run over ChipVerilog's or1200.
    row = (
        "[2]      STX_VE_481           Syntax      or1200_ctrl.v     241     1     "
        "Syntax error near ( ; )"
    )
    (parsed,) = cr.parse_rows(row)
    assert parsed["sev_token"] == "Syntax"
    # SpyGlass registers it FATAL, so it gates.
    assert cr.normalize_severity("Syntax") == "error"


def test_parse_rows_alias_variants_and_native_id():
    rows = cr.parse_rows(MIXED)
    assert len(rows) == 4
    # multi-word alias row: severity is the last token, rule preserved, native id captured
    warn = [r for r in rows if r["rule"] == "Ac_conv04"][0]
    assert warn["sev_token"] == "Warning" and warn["native_id"] == "F8"
    # empty-alias row parses as Info
    info = [r for r in rows if r["rule"] == "W240"][0]
    assert info["sev_token"] == "Info"


def test_count_raw_includes_synthesiserror_as_error():
    assert cr.count_raw(cr.parse_rows(MIXED)) == {"error": 2, "warning": 1, "info": 1}


def test_count_raw_none_on_unknown_severity():
    assert cr.count_raw(cr.parse_rows(UNKNOWN_SEV)) is None


def test_build_violations_all_rows_with_native_and_synth_id():
    rows = cr.parse_rows(COLLISION)
    vs = cr.build_violations(rows)
    assert [v["id"] for v in vs] == [
        "W123:../../../rtl-design/x.v:42",
        "W123:../../../rtl-design/x.v:42#2",
    ]
    assert [v["native_id"] for v in vs] == ["A1", "A2"]


def test_main_rejects_bad_arg_exit2():
    assert cr.main(["collect_report.py", "bogus"]) == 2


# ── run() exit-code contract ─────────────────────────────────────────────────
def test_run_clean_exit0(tmp_path):
    stage(tmp_path, CLEAN)
    assert cr.run("cdc", tmp_path) == 0
    data = json.loads((tmp_path / "cdc-violations.json").read_text())
    assert data["counts"] == {"error": 0, "warning": 0, "info": 0}
    assert data["violations"] == []
    assert data["totals"]["reported"] == 0
    assert (tmp_path / "cdc-report.txt").exists()


def test_run_mixed_exit0(tmp_path):
    stage(tmp_path, MIXED)
    assert cr.run("cdc", tmp_path) == 0
    data = json.loads((tmp_path / "cdc-violations.json").read_text())
    assert data["counts"] == {"error": 2, "warning": 1, "info": 1}
    assert data["totals"] == {
        "generated": 4,
        "waived": 0,
        "reported": 4,
        "overlimit": 0,
    }
    assert len(data["violations"]) == 4
    errs = [v for v in data["violations"] if v["severity"] == "error"]
    assert {v["native_id"] for v in errs} == {"4F", "2"}


def test_run_missing_exit1(tmp_path):
    (tmp_path / "spyglass_work").mkdir()
    assert cr.run("cdc", tmp_path) == 1


def test_run_no_header_exit3(tmp_path):
    stage(tmp_path, NO_HEADER)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_parse_gap_exit3(tmp_path):
    stage(tmp_path, PARSE_GAP)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_unknown_severity_exit3(tmp_path):
    stage(tmp_path, UNKNOWN_SEV)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_count_mismatch_exit3(tmp_path):
    stage(tmp_path, COUNT_MISMATCH)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_header_integrity_exit3(tmp_path):
    stage(tmp_path, INTEGRITY)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_overlimit_exit3(tmp_path):
    stage(tmp_path, OVERLIMIT)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_removes_stale_on_failure(tmp_path):
    stage(tmp_path, CLEAN)
    assert cr.run("cdc", tmp_path) == 0
    src = tmp_path / "spyglass_work/cdc/cdc_verify_struct/spyglass/moresimple.rpt"
    src.write_text(NO_HEADER)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_location_precedence_verify_struct_wins(tmp_path):
    stage(tmp_path, MIXED, "cdc/cdc_verify_struct/spyglass")
    setup = tmp_path / "spyglass_work/cdc/cdc_setup/spyglass"
    setup.mkdir(parents=True)
    (setup / "cdc_setup.rpt").write_text(CLEAN)
    got = cr.locate("cdc", tmp_path / "spyglass_work").as_posix()
    assert got.endswith("cdc_verify_struct/spyglass/moresimple.rpt")


@pytest.mark.parametrize("goal", ["cdc_setup", "cdc_setup_check"])
def test_setup_only_cannot_publish_cdc_verdict_inputs(tmp_path, goal):
    stage(tmp_path, CLEAN, f"top/cdc/{goal}/spyglass_reports")
    source = tmp_path / f"spyglass_work/top/cdc/{goal}/spyglass_reports/moresimple.rpt"
    for name in ("cdc-report.txt", "cdc-violations.json"):
        (tmp_path / name).write_text("previous result")

    assert cr.run("cdc", tmp_path) == 1
    assert not (tmp_path / "cdc-report.txt").exists()
    assert not (tmp_path / "cdc-violations.json").exists()
    assert source.read_text() == CLEAN


@pytest.mark.parametrize("design_alias", [False, True])
def test_structural_report_and_waivers_survive_both_native_locations(
    tmp_path, design_alias
):
    work = tmp_path / "spyglass_work"
    report_dir = work / "project/consolidated_reports/core_cdc_cdc_verify_struct"
    report_dir.mkdir(parents=True)
    source = report_dir / "moresimple.rpt"
    source.write_text(hdr(1, 1, 0, 0))
    waiver = hdr(1, 1, 0, 0) + (
        "Waiver comment : See design rationale.\n"
        "[4] Ac_unsync01 Warning core.v 1 10 Crossing uses a reviewed protocol\n"
    )
    source.with_name("waiver.rpt").write_text(waiver)
    if design_alias:
        aliases = work / "project/core/cdc/cdc_verify_struct/spyglass_reports"
        aliases.mkdir(parents=True)
        for name in ("moresimple.rpt", "waiver.rpt"):
            (aliases / name).symlink_to(report_dir / name)
    stage(tmp_path, MIXED, "project/core/cdc/cdc_setup/spyglass_reports")

    assert cr.run("cdc", tmp_path) == 0
    data = json.loads((tmp_path / "cdc-violations.json").read_text())
    assert Path(data["source"]).resolve() == source
    assert data["totals"]["waived"] == 1
    assert data["counts"] == {"error": 0, "warning": 0, "info": 0}
    assert waiver in (tmp_path / "cdc-report.txt").read_text()
