"""Reap-time cost_tokens instrumentation (P0 workstream (1), component C2)."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = str(ROOT / "framework" / "scripts" / "kernel.py")
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_json(tmp_path, *args):
    r = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _write(module, rel, content):
    p = facts.module_root(module) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


# Minimal declared outputs + stage_specific so dispatch is available and the
# reap-time schema validation genuinely passes (mirrors test_kernel_cli).
_STAGE_SPECIFIC = {
    "specification": {"top_module": "top"},
    "simulation-plan": {},
    "rtl-design": {},
    "lint-cdc": {"violations": []},
}
_STAGE_FILES = {
    "specification": {
        "design.md": "d",
        "manifest.json": "{}",
        "ppa.json": "{}",
        "constraints/top.sdc": "# sdc",
        "constraints/top.sgdc": "# sgdc",
    },
    "simulation-plan": {
        "verification-plan.md": "p",
        "scaffold-specification.json": "{}",
    },
    "rtl-design": {
        "top.v": "module top; endmodule",
        "filelist.txt": "top.v",
        "README.md": "r",
    },
    "lint-cdc": {"lint-report.txt": "clean", "cdc-report.txt": "clean"},
}


def _dwr(tmp_path, module, rule, *, trace=None):
    """dispatch + write pass result + reap; optionally pass --subagent-output-file."""
    d = _run_json(tmp_path, "dispatch", "--module", module, "--rule", rule)
    assert d["ok"], d
    wd = d["workdir"]
    for rel, c in _STAGE_FILES[rule].items():
        _write(module, f"{wd}/{rel}", c)
    result = {
        "schema_version": 1,
        "stage": rule,
        "module": module,
        "produced_at": _now_iso(),
        "status": "pass",
        "artifacts": [{"path": p} for p in _STAGE_FILES[rule]],
        "stage_specific": _STAGE_SPECIFIC[rule],
    }
    _write(module, f"{wd}/result.json", json.dumps(result))
    args = ["reap", "--module", module, "--rule", rule, "--run", str(d["run"])]
    if trace is not None:
        args += ["--subagent-output-file", str(trace)]
    return _run_json(tmp_path, *args)


def _latest_outcome(module, rule):
    outs = [
        e
        for e in facts.read_events(module)
        if e["type"] == "outcome" and e["rule"] == rule
    ]
    assert outs, f"no outcome for {rule}"
    return outs[-1]


def _streaming_trace(path):
    """msgA over two streaming lines (dedup target) + single-line msgB."""

    def line(mid, out, inp, cc, cr):
        return json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": mid,
                    "role": "assistant",
                    "model": "claude-x",
                    "usage": {
                        "input_tokens": inp,
                        "output_tokens": out,
                        "cache_creation_input_tokens": cc,
                        "cache_read_input_tokens": cr,
                    },
                },
            }
        )

    path.write_text(
        "\n".join(
            [
                line("msgA", 2, 10, 100, 5),
                line("msgA", 50, 10, 100, 5),
                line("msgB", 30, 8, 0, 200),
            ]
        )
        + "\n"
    )


def _chain_to_lintcdc(tmp_path, module):
    _write(module, "brainstorm.md", "b")
    for rule in ("specification", "simulation-plan", "rtl-design"):
        o = _dwr(tmp_path, module, rule)
        assert o["verdict"] == "pass", o


def test_reap_writes_cost_tokens_from_trace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _chain_to_lintcdc(tmp_path, "m")
    trace = tmp_path / "a_agent.output"
    _streaming_trace(trace)
    o = _dwr(tmp_path, "m", "lint-cdc", trace=trace)
    assert o["verdict"] == "pass"
    ct = _latest_outcome("m", "lint-cdc")["cost_tokens"]
    assert ct["input_tokens"] == 18
    assert ct["output_tokens"] == 80  # deduped msgA final (not 2+50)
    assert ct["total_tokens"] == 403  # 18+80+100+205
    assert ct["message_count"] == 2
    assert ct["source"] == "subagent_trace"


def test_reap_without_trace_omits_cost_tokens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _chain_to_lintcdc(tmp_path, "m")
    o = _dwr(tmp_path, "m", "lint-cdc")  # no --subagent-output-file
    assert o["verdict"] == "pass"
    assert "cost_tokens" not in _latest_outcome("m", "lint-cdc")


def test_reap_garbage_trace_ok_and_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _chain_to_lintcdc(tmp_path, "m")
    trace = tmp_path / "bad.output"
    trace.write_text("not json\n{bad\n")  # non-empty so it mirrors, but unparseable
    o = _dwr(tmp_path, "m", "lint-cdc", trace=trace)
    assert o["verdict"] == "pass"  # cost never blocks reap
    ct = _latest_outcome("m", "lint-cdc")["cost_tokens"]
    assert ct["total_tokens"] == 0
    assert ct["source"] == "subagent_trace"
