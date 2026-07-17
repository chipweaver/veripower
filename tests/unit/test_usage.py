"""Tests for framework/scripts/usage.py — CC-JSONL token-usage parser (C1)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import usage  # noqa: E402


def _assistant_line(mid, out_tok, inp=0, cc=0, cr=0, model="claude-x"):
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": mid,
                "role": "assistant",
                "model": model,
                "usage": {
                    "input_tokens": inp,
                    "output_tokens": out_tok,
                    "cache_creation_input_tokens": cc,
                    "cache_read_input_tokens": cr,
                },
            },
        }
    )


def test_dedup_by_message_id_keeps_final_line(tmp_path):
    f = tmp_path / "t.output"
    f.write_text(
        "\n".join(
            [
                _assistant_line("msgA", 2, inp=10, cc=100, cr=5),  # partial
                _assistant_line(
                    "msgA", 50, inp=10, cc=100, cr=5
                ),  # final (output grew)
                _assistant_line("msgB", 30, inp=8, cc=0, cr=200),  # single-line message
                json.dumps(
                    {"type": "user", "message": {"content": "hi"}}
                ),  # no usage -> skip
                "{ not valid json",  # bad -> skip
            ]
        )
        + "\n"
    )
    u = usage.parse_trace_usage(f)
    assert u["input_tokens"] == 18  # 10 + 8 (msgA counted ONCE)
    assert u["output_tokens"] == 80  # 50 + 30 (msgA final, not 2+50)
    assert u["cache_creation_input_tokens"] == 100
    assert u["cache_read_input_tokens"] == 205
    assert u["total_tokens"] == 403  # 18+80+100+205
    assert u["message_count"] == 2
    assert u["models"] == ["claude-x"]


def test_missing_file_returns_zero(tmp_path):
    u = usage.parse_trace_usage(tmp_path / "nope.output")
    assert u["total_tokens"] == 0 and u["message_count"] == 0 and u["models"] == []


def test_empty_file_returns_zero(tmp_path):
    f = tmp_path / "e.output"
    f.write_text("")
    assert usage.parse_trace_usage(f)["total_tokens"] == 0


def test_all_garbage_lines_returns_zero(tmp_path):
    f = tmp_path / "g.output"
    f.write_text("not json\n{bad\n\n")
    assert usage.parse_trace_usage(f)["total_tokens"] == 0


_REAL_TRACE = (
    ROOT
    / "asic"
    / "fa_core_fsa"
    / "Design"
    / "synthesis"
    / "runs"
    / "1"
    / ".subagent_traces"
    / "synthesis-a986209eb6c5a1902.output"
)


@pytest.mark.skipif(not _REAL_TRACE.exists(), reason="real fixture trace absent")
def test_real_trace_smoke():
    u = usage.parse_trace_usage(_REAL_TRACE)
    assert u["message_count"] > 0
    assert u["total_tokens"] > 0
    # total is exactly the sum of the four classes (dedup consistency)
    assert u["total_tokens"] == (
        u["input_tokens"]
        + u["output_tokens"]
        + u["cache_creation_input_tokens"]
        + u["cache_read_input_tokens"]
    )
