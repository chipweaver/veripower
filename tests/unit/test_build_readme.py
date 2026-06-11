# tests/unit/test_build_readme.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/rtl-design/scripts/build_readme.py"


def _run(ledger, top, out, check=True):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--ledger",
            str(ledger),
            "--top",
            top,
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def _ledger(tmp_path, obj):
    p = tmp_path / ".child_reports.json"
    p.write_text(json.dumps(obj))
    return p


def test_top_module_line_verbatim(tmp_path):
    # The exact line bootstrap_synthesis.sh:79 greps — must stay byte-stable.
    led = _ledger(
        tmp_path, {"a": {"files": ["a.sv"], "annotations": {"sgdc": {}, "sdc": {}}}}
    )
    out = tmp_path / "README.md"
    _run(led, "my_top", out)
    assert "**Top module**: my_top" in out.read_text()


def test_top_line_is_first_C3(tmp_path):
    # bootstrap greps the FIRST 'top'-matching line (head -1); a `sync_cell -name top_*`
    # annotation line also matches 'top', so the Top line must be line 1.
    led = _ledger(
        tmp_path,
        {
            "a": {
                "files": ["a.sv"],
                "annotations": {
                    "sgdc": {
                        "sync_cell": ["top_sync"],
                        "reset_synchronizer": [],
                        "set_case_analysis": [],
                        "quasi_static": [],
                    },
                    "sdc": {},
                },
            }
        },
    )
    out = tmp_path / "README.md"
    _run(led, "real_top", out)
    assert out.read_text().splitlines()[0] == "**Top module**: real_top"


def test_empty_annotations_render_fallbacks(tmp_path):
    led = _ledger(
        tmp_path, {"a": {"files": ["a.sv"], "annotations": {"sgdc": {}, "sdc": {}}}}
    )
    out = tmp_path / "README.md"
    _run(led, "t", out)
    text = out.read_text()
    assert "single clock domain; no deep annotations needed." in text
    assert "set_false_path: none" in text


def test_sgdc_and_sdc_annotations_aggregated(tmp_path):
    led = _ledger(
        tmp_path,
        {
            "leaf": {
                "files": ["s.sv"],
                "annotations": {
                    "sgdc": {
                        "sync_cell": ["cdc_sync_2ff"],
                        "reset_synchronizer": [],
                        "set_case_analysis": [],
                        "quasi_static": [],
                    },
                    "sdc": {
                        "create_generated_clock": [
                            {"module": "clkdiv", "pin": "clk_div2"}
                        ],
                        "set_multicycle_path": [],
                        "set_false_path": [],
                    },
                },
            },
            "top": {
                "files": ["t.sv"],
                "annotations": {
                    "sgdc": {
                        "sync_cell": [],
                        "reset_synchronizer": [],
                        "set_case_analysis": [{"port": "scan_en", "value": 0}],
                        "quasi_static": ["cfg_word"],
                    },
                    "sdc": {
                        "create_generated_clock": [],
                        "set_multicycle_path": [],
                        "set_false_path": [],
                    },
                },
            },
        },
    )
    out = tmp_path / "README.md"
    _run(led, "top", out)
    text = out.read_text()
    assert "sync_cell -name cdc_sync_2ff" in text
    assert "set_case_analysis 0 scan_en" in text
    assert "quasi_static -name cfg_word" in text
    assert "clkdiv.clk_div2" in text
    # SGDC content precedes SDC content (stable section order)
    assert text.index("### SGDC") < text.index("### SDC")


def test_fail_loud_on_malformed_ledger_F8(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"a": {"files": ["a.sv"]}}')  # missing annotations
    out = tmp_path / "README.md"
    r = _run(bad, "t", out, check=False)
    assert r.returncode == 1
    assert not out.exists()  # no degraded output
