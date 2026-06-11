"""Tests for skills/lint-cdc/templates/scripts/collect_report.py (grounded format)."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "lint-cdc" / "templates" / "scripts"))

import collect_report as cr  # noqa: E402


# ── fixtures: faithful real SpyGlass vL-2016.06 moresimple.rpt format ─────────
def _hdr(generated, waived, reported, overlimit):
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


CLEAN = _hdr(0, 0, 0, 0) + "(no reported messages)\n"

# 4 reported rows: Error, SynthesisError, Warning(multi-word alias), Info(empty alias)
MIXED = _hdr(4, 0, 4, 0) + (
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
PARSE_GAP = _hdr(2, 0, 2, 0) + (
    "[4F]     STARC05   AsyncResetOtherUse   Warning   ../../../rtl-design/a.v   171   10   ok row\n"
    "[XX]     BadRow    truncated line with no numeric columns\n"
)

# a row whose severity token is not error/warning/info
UNKNOWN_SEV = _hdr(1, 0, 1, 0) + (
    "[4F]     SomeRule   SomeAlias   Note   ../../../rtl-design/a.v   10   5   unexpected severity\n"
)

# reported says 5 but only 1 bracket row present
COUNT_MISMATCH = _hdr(5, 0, 5, 0) + (
    "[4F]     R   A   Warning   ../../../rtl-design/a.v   1   1   m\n"
)

# generated(10) != waived(2) + reported(4)
INTEGRITY = _hdr(10, 2, 4, 0) + (
    "[1]   R   A   Warning   ../../../rtl-design/a.v   1   1   m\n"
    "[2]   R   A   Warning   ../../../rtl-design/b.v   2   1   m\n"
    "[3]   R   A   Info      ../../../rtl-design/c.v   3   1   m\n"
    "[4]   R   A   Info      ../../../rtl-design/d.v   4   1   m\n"
)

# overlimit > 0 (other checks pass)
OVERLIMIT = _hdr(4, 0, 4, 3) + (
    "[1]   R   A   Warning   ../../../rtl-design/a.v   1   1   m\n"
    "[2]   R   A   Warning   ../../../rtl-design/b.v   2   1   m\n"
    "[3]   R   A   Info      ../../../rtl-design/c.v   3   1   m\n"
    "[4]   R   A   Info      ../../../rtl-design/d.v   4   1   m\n"
)

# two rows colliding on rule:file:line
COLLISION = _hdr(2, 0, 2, 0) + (
    "[A1]   W123   AliasX   Warning   ../../../rtl-design/x.v   42   10   net alpha undriven\n"
    "[A2]   W123   AliasX   Warning   ../../../rtl-design/x.v   42   10   net beta undriven\n"
)


def _stage(root, body, stage_path="cdc/cdc_verify_struct/spyglass"):
    d = root / "spyglass_work" / stage_path
    d.mkdir(parents=True, exist_ok=True)
    (d / "moresimple.rpt").write_text(body)
    (root / "env.sh").write_text('export TOP="${TOP:-spi_master}"\n')


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
        cr._sev(t) for t in ("Fatal", "Error", "SynthesisError", "Warning", "Info")
    ] == ["error", "error", "error", "warning", "info"]
    assert cr._sev("Note") is None


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
    _stage(tmp_path, CLEAN)
    assert cr.run("cdc", tmp_path) == 0
    data = json.loads((tmp_path / "cdc-violations.json").read_text())
    assert data["counts"] == {"error": 0, "warning": 0, "info": 0}
    assert data["violations"] == []
    assert data["totals"]["reported"] == 0
    assert (tmp_path / "cdc-report.txt").exists()


def test_run_mixed_exit0(tmp_path):
    _stage(tmp_path, MIXED)
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
    _stage(tmp_path, NO_HEADER)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_parse_gap_exit3(tmp_path):
    _stage(tmp_path, PARSE_GAP)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_unknown_severity_exit3(tmp_path):
    _stage(tmp_path, UNKNOWN_SEV)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_count_mismatch_exit3(tmp_path):
    _stage(tmp_path, COUNT_MISMATCH)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_header_integrity_exit3(tmp_path):
    _stage(tmp_path, INTEGRITY)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_overlimit_exit3(tmp_path):
    _stage(tmp_path, OVERLIMIT)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_removes_stale_on_failure(tmp_path):
    _stage(tmp_path, CLEAN)
    assert cr.run("cdc", tmp_path) == 0
    src = tmp_path / "spyglass_work/cdc/cdc_verify_struct/spyglass/moresimple.rpt"
    src.write_text(NO_HEADER)
    assert cr.run("cdc", tmp_path) == 3
    assert not (tmp_path / "cdc-violations.json").exists()


def test_run_location_precedence_verify_struct_wins(tmp_path):
    _stage(tmp_path, MIXED, "cdc/cdc_verify_struct/spyglass")
    setup = tmp_path / "spyglass_work/cdc/cdc_setup/spyglass"
    setup.mkdir(parents=True)
    (setup / "cdc_setup.rpt").write_text(CLEAN)
    got = cr.locate("cdc", tmp_path / "spyglass_work").as_posix()
    assert got.endswith("cdc_verify_struct/spyglass/moresimple.rpt")
