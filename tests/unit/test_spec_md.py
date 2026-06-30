# tests/unit/test_spec_md.py
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/specification/scripts"
MAIN = SCRIPTS / "spec" / "__main__.py"
sys.path.insert(0, str(SCRIPTS))
from spec._md import extract_section, parse_markdown_table  # noqa: E402

_DOC = (
    "# T\n\n"
    "## 1.6 Clocks\n\n"
    "| Clock Name | SDC Period (ns) |\n"
    "|---|---|\n"
    "| clk | 2.0 |\n\n"
    "## 1.7 Next\n\nignored\n"
)


def test_extract_section_stops_at_same_or_shallower_heading():
    sec = extract_section(_DOC, r"§?\s*1\.6.*Clocks")
    assert "clk" in sec and "ignored" not in sec


def test_parse_markdown_table_skips_divider_row():
    rows = parse_markdown_table(extract_section(_DOC, r"§?\s*1\.6.*Clocks"))
    assert rows == [{"Clock Name": "clk", "SDC Period (ns)": "2.0"}]


def test_parse_markdown_table_honors_escaped_pipe():
    # A literal '|' inside a cell is markdown-escaped as '\|' and MUST NOT split the
    # column; the parser must unescape it back to '|'. Without this, the escaped cell
    # is over-split and every downstream column shifts right.
    table = "| A | B | C |\n|---|---|---|\n| x | a \\| b \\| c | y |\n"
    assert parse_markdown_table(table) == [{"A": "x", "B": "a | b | c", "C": "y"}]


def test_cli_help_lists_all_five_verbs():
    r = subprocess.run(["python3", str(MAIN), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for verb in (
        "derive-ports",
        "check-coverage",
        "derive-constraints",
        "validate-review",
        "finalize",
    ):
        assert verb in r.stdout


def test_cli_unknown_verb_exits_2():
    r = subprocess.run(["python3", str(MAIN), "bogus"], capture_output=True, text=True)
    assert r.returncode == 2
