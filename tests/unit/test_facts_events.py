import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import store  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def append(module, ev):
    store.append_event(module, ev, TS)


def test_append_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    append(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "Design/specification/runs/1",
            "params": {},
        },
    )
    evs = store.read_events("m")
    assert len(evs) == 1 and evs[0]["ts"] == TS and evs[0]["type"] == "dispatch"


def test_append_rejects_schema_violation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        append(
            "m", {"type": "dispatch", "rule": "specification"}
        )  # missing run/workdir/...


def test_run_number_and_in_flight(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    append(
        "m",
        {
            "type": "dispatch",
            "rule": "rtl-design",
            "run": 1,
            "workdir": "w",
            "params": {},
        },
    )
    evs = store.read_events("m")
    assert (
        sum(
            1
            for event in evs
            if event["type"] == "dispatch" and event["rule"] == "rtl-design"
        )
        == 1
    )
    assert facts.in_flight(evs) == [{"rule": "rtl-design", "run": 1}]
    append(
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
    assert facts.in_flight(store.read_events("m")) == []


def test_truncated_last_line_prevents_reads_and_appends(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    append("m", {"type": "signoff", "provenance": "test", "reason": "r"})
    p = Path("m") / "events.jsonl"
    p.write_text(p.read_text() + '{"type": "outcom')  # truncated
    before = p.read_bytes()
    with pytest.raises(SystemExit, match="corrupt line 2"):
        store.read_events("m")
    with pytest.raises(SystemExit, match="corrupt line 2"):
        append("m", {"type": "signoff", "provenance": "test", "reason": "next"})
    assert p.read_bytes() == before


def test_complete_record_without_newline_can_be_followed(tmp_path):
    module = str(tmp_path)
    event = {"type": "signoff", "provenance": "test", "reason": "first"}
    append(module, event)
    p = Path(module) / "events.jsonl"
    p.write_bytes(p.read_bytes().rstrip(b"\n"))
    append(module, {**event, "reason": "second"})
    assert [e["reason"] for e in store.read_events(module)] == ["first", "second"]


def test_append_write_failure_preserves_previous_log(tmp_path, monkeypatch):
    module = str(tmp_path)
    event = {"type": "signoff", "provenance": "test", "reason": "first"}
    append(module, event)
    before = (Path(module) / "events.jsonl").read_bytes()

    def _fail_write(*args):
        raise OSError("publication interrupted")

    monkeypatch.setattr(store.os, "write", _fail_write)
    with pytest.raises(OSError, match="publication interrupted"):
        append(module, {**event, "reason": "second"})
    assert (Path(module) / "events.jsonl").read_bytes() == before


def test_read_events_mid_file_corruption_errors(tmp_path, monkeypatch):
    # An unreadable event must not disappear from the history.
    monkeypatch.chdir(tmp_path)
    good = '{"type":"signoff","ts":"t","provenance":"test","reason":"r"}'
    p = Path("m") / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(good + "\n" + "THIS-IS-CORRUPT-NOT-JSON\n" + good + "\n")
    with pytest.raises(SystemExit):
        store.read_events("m")


def test_concurrent_appends_keep_both_records(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)
    dumps = store.json.dumps

    def _serialize_together(value, *args, **kwargs):
        encoded = dumps(value, *args, **kwargs)
        if (
            isinstance(value, dict)
            and value.get("type") == "dispatch"
            and "ts" in value
        ):
            barrier.wait(timeout=5)
        return encoded

    monkeypatch.setattr(store.json, "dumps", _serialize_together)
    with ThreadPoolExecutor(2) as pool:
        writes = [
            pool.submit(
                append,
                str(tmp_path),
                {
                    "type": "dispatch",
                    "rule": rule,
                    "run": 1,
                    "workdir": f"{rule}/runs/1",
                    "params": {},
                },
            )
            for rule in ("specification", "rtl-design")
        ]
        for write in writes:
            write.result()
    assert {e["rule"] for e in store.read_events(str(tmp_path))} == {
        "specification",
        "rtl-design",
    }


def test_short_append_raises_and_prevents_further_mutations(tmp_path, monkeypatch):
    module = str(tmp_path)
    event = {"type": "signoff", "provenance": "test", "reason": "first"}
    append(module, event)
    previous = (Path(module) / "events.jsonl").read_bytes()
    write = store.os.write
    monkeypatch.setattr(store.os, "write", lambda fd, data: write(fd, data[:5]))
    with pytest.raises(OSError, match="incomplete write"):
        append(module, {**event, "reason": "second"})
    damaged = (Path(module) / "events.jsonl").read_bytes()
    assert damaged.startswith(previous)
    monkeypatch.setattr(store.os, "write", write)
    with pytest.raises(SystemExit, match="corrupt line"):
        append(module, {**event, "reason": "third"})
    assert (Path(module) / "events.jsonl").read_bytes() == damaged
