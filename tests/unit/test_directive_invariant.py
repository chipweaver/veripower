"""Freeze the `directive` lifecycle (kernel.py) — the Task C6 rename of the old
`orchestrator_context` channel (which lived in the now-retired old kernel CLI).

The `directive` channel: a caller passes `--directive <file|->` to `kernel.py
dispatch`; `cmd_dispatch` writes `<workdir>/directive.md` and records
`{"path": ..., "digest": ...}` under the dispatch event's `params.directive`
(module-root-relative path). The dispatched stage skill reads that sibling file
(`{directive_path}` in its Input Artifacts table).

Invariants this module locks against regression — the kernel-side analogs of the
retired test_orchestrator_context_invariant.py's I1-I6:

I1 — Round-trip: content in -> file at the recorded path contains the content
I2 — Absent when no directive_path is given: no `directive` key in the dispatch
     event's params
I3 — Recorded path is module-root-relative (no leading `/`, no `asic/` prefix)
I4 — Path includes the dispatched run number
I5 — Not promoted to canonical: the per-dispatch hint stays under `runs/<N>/`;
     `store.promote()` only lifts `result.json.artifacts[]` entries, so
     `directive.md` (never listed there) never reaches `Design/<stage>/directive.md`
I6 — Compute-phase write: if the `directive.md` write raises, no dispatch event
     has been appended (the write happens before `facts.append_event` in
     `cmd_dispatch`)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import kernel  # noqa: E402
import rules  # noqa: E402


def _now_iso() -> str:
    """Fresh second-resolution UTC stamp (mirrors skill finalizers) so a mid-test
    result.json passes the reap temporal-integrity check."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_file(module: str, rel: str, content: str) -> Path:
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _dispatch(module, rule="specification", directive_path=None):
    return kernel.cmd_dispatch(module, rule, "delivery", directive_path, None)


def _latest_dispatch_event(module, rule):
    events = facts.read_events(module)
    return next(
        e for e in reversed(events) if e["type"] == "dispatch" and e["rule"] == rule
    )


def test_i1_roundtrip_content_written(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_file("M1", "brainstorm.md", "b1")
    hint = tmp_path / "hint.md"
    hint.write_text("hint: focus on FSM coverage")

    r = _dispatch("M1", directive_path=str(hint))
    assert r["ok"], r

    ev = _latest_dispatch_event("M1", "specification")
    rel = ev["params"]["directive"]["path"]
    f = facts.module_root("M1") / rel
    assert f.is_file()
    assert f.read_text() == "hint: focus on FSM coverage"


def test_i2_absent_when_no_directive(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_file("M1", "brainstorm.md", "b1")

    r = _dispatch("M1")
    assert r["ok"], r

    ev = _latest_dispatch_event("M1", "specification")
    assert "directive" not in ev["params"]
    assert not (facts.module_root("M1") / r["workdir"] / "directive.md").exists()


def test_i3_path_is_module_root_relative(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_file("M1", "brainstorm.md", "b1")
    hint = tmp_path / "hint.md"
    hint.write_text("x")

    _dispatch("M1", directive_path=str(hint))
    ev = _latest_dispatch_event("M1", "specification")
    rel = ev["params"]["directive"]["path"]
    assert not rel.startswith("/"), f"expected a relative path, got {rel!r}"
    assert not rel.startswith("asic/"), (
        f"path is module-root-relative; the asic/<module>/ prefix must be "
        f"stripped, got {rel!r}"
    )


def test_i4_path_includes_dispatched_run_number(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_file("M1", "brainstorm.md", "b1")
    hint = tmp_path / "hint.md"
    hint.write_text("x")

    r = _dispatch("M1", directive_path=str(hint))
    ev = _latest_dispatch_event("M1", "specification")
    rel = ev["params"]["directive"]["path"]
    assert f"runs/{r['run']}/" in rel, (
        f"path should sit under runs/{r['run']}/, got {rel!r}"
    )


def test_i5_not_promoted_to_canonical(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_file("M1", "brainstorm.md", "b1")
    hint = tmp_path / "hint.md"
    hint.write_text("rework hint")

    r = _dispatch("M1", directive_path=str(hint))
    assert r["ok"], r
    workdir = r["workdir"]
    _write_file("M1", f"{workdir}/design.md", "design v1")
    result = {
        "stage": "specification",
        "module": "M1",
        "produced_at": _now_iso(),
        "status": "pass",
        "artifacts": [{"path": "design.md"}],
        "stage_specific": {"top_module": "top", "ppa_targets": []},
    }
    _write_file("M1", f"{workdir}/result.json", json.dumps(result))

    res = kernel.cmd_reap("M1", "specification", r["run"])
    assert res["ok"] and res["verdict"] == "pass", res

    canonical_dir = facts.module_root("M1") / Path(*rules.workdir_root("specification"))
    assert not (canonical_dir / "directive.md").exists(), (
        "directive.md must not be promoted to canonical (ephemeral per-dispatch hint)"
    )
    assert (facts.module_root("M1") / workdir / "directive.md").is_file(), (
        "the run-specific copy is retained"
    )


def test_i6_no_dispatch_event_on_write_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_file("M1", "brainstorm.md", "b1")
    hint = tmp_path / "hint.md"
    hint.write_text("should not survive")

    real_write_bytes = Path.write_bytes

    def fake_write_bytes(self, data, *args, **kwargs):
        if self.name == "directive.md":
            raise OSError("simulated write failure")
        return real_write_bytes(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", fake_write_bytes)

    raised = False
    try:
        _dispatch("M1", directive_path=str(hint))
    except OSError:
        raised = True
    assert raised, "expected OSError to propagate from the directive.md write"

    events = facts.read_events("M1")
    dispatch_events = [e for e in events if e["type"] == "dispatch"]
    assert dispatch_events == [], (
        f"directive.md write failure must short-circuit before event append; "
        f"found {len(dispatch_events)} dispatch event(s)"
    )
