import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def _append(module, ev):
    facts.append_event(module, ev, TS)


def test_append_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _append(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "Design/specification/runs/1",
            "params": {},
        },
    )
    evs = facts.read_events("m")
    assert len(evs) == 1 and evs[0]["ts"] == TS and evs[0]["type"] == "dispatch"


def test_append_rejects_schema_violation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        _append(
            "m", {"type": "dispatch", "rule": "specification"}
        )  # missing run/workdir/...


def test_run_number_and_in_flight(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _append(
        "m",
        {
            "type": "dispatch",
            "rule": "rtl-design",
            "run": 1,
            "workdir": "w",
            "params": {},
        },
    )
    evs = facts.read_events("m")
    assert facts.runs_of(evs, "rtl-design") == 1
    assert facts.in_flight(evs) == [{"rule": "rtl-design", "run": 1}]
    _append(
        "m",
        {
            "type": "outcome",
            "rule": "rtl-design",
            "run": 1,
            "verdict": "pass",
            "outputs": {},
            "proofs": [],
            "tool_versions": {},
        },
    )
    assert facts.in_flight(facts.read_events("m")) == []


def test_truncated_last_line_tolerated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _append("m", {"type": "reopen", "pin_ref": "spec-review", "reason": "r"})
    p = facts.events_path("m")
    p.write_text(p.read_text() + '{"type": "outcom')  # truncated
    assert len(facts.read_events("m")) == 1


def test_read_events_mid_file_corruption_errors(tmp_path, monkeypatch):
    # ONLY a truncated LAST line is tolerated. A corrupt line in the MIDDLE
    # is silently skipped today -> a dropped dispatch line -> run-number reuse. It must be a
    # hard error (conservative — never proceed on a corrupt append-only log).
    monkeypatch.chdir(tmp_path)
    good = '{"type":"reopen","ts":"t","pin_ref":"spec-review","reason":"r"}'
    p = facts.events_path("m")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(good + "\n" + "THIS-IS-CORRUPT-NOT-JSON\n" + good + "\n")
    with pytest.raises(SystemExit):
        facts.read_events("m")
