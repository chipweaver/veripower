"""Log -> cost metrics aggregator (P0 workstream (4), component C3).

Reads a run manifest and, per full run, computes:
  task_tokens       — sum over Task-execution stage outcomes:
                      outcome.cost_tokens if present (kernel instrumentation),
                      else a re-scan of that run's .subagent_traces/ (covers
                      pre-instrumentation runs; usage.parse_trace_usage).
  mainthread_tokens — sum over the run's orchestrator session transcript(s)
                      (main-thread stages + orchestrator overhead).
  total_tokens      — task_tokens + mainthread_tokens (no double count:
                      sidechain turns are not in the session transcript).
  wallclock_sec     — sum of (outcome.ts - matching dispatch.ts).

Cost is audit-only. Quality columns (pass@1 etc.) are left blank here and
joined later once the arm-blind adjudication harness (workstream (3)) lands.

Run:  python eval/aggregate/aggregate.py --manifest <p.json> --out <prefix>
Writes <prefix>.json and <prefix>.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[2] / "framework" / "scripts"))
import rules  # noqa: E402
import usage  # noqa: E402

_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _read_events(repo_root: Path, module: str) -> list[dict]:
    p = repo_root / "asic" / module / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _rescan_task_trace(repo_root: Path, module: str, rule: str, run: int) -> dict:
    """Sum usage across a run's mirrored .subagent_traces/*.output."""
    tdir = (
        repo_root
        / "asic"
        / module
        / Path(*rules.workdir_root(rule))
        / "runs"
        / str(run)
        / ".subagent_traces"
    )
    agg = {k: 0 for k in _TOKEN_KEYS}
    agg["total_tokens"] = 0
    found = False
    if tdir.is_dir():
        for f in sorted(tdir.glob("*.output")):
            found = True
            u = usage.parse_trace_usage(f)
            for k in _TOKEN_KEYS:
                agg[k] += u[k]
            agg["total_tokens"] += u["total_tokens"]
    return {"usage": agg, "found": found}


def _task_cost(repo_root: Path, module: str, events: list[dict]) -> dict:
    """Sum Task-execution stage cost; per outcome prefer cost_tokens, else
    re-scan the trace. Returns {usage breakdown, partial}."""
    agg = {k: 0 for k in _TOKEN_KEYS}
    agg["total_tokens"] = 0
    partial = False
    for e in events:
        if e.get("type") != "outcome":
            continue
        rule = e.get("rule")
        r = rules.RULES.get(rule)
        if r is None or getattr(r, "execution", None) != "task":
            continue  # main-thread cost lives in the session transcript
        ct = e.get("cost_tokens")
        if ct and isinstance(ct.get("total_tokens"), int):
            src = ct
        else:
            rescan = _rescan_task_trace(repo_root, module, rule, e["run"])
            src = rescan["usage"]
            if not rescan["found"]:
                partial = True  # no cost_tokens AND no trace on disk
        for k in _TOKEN_KEYS:
            agg[k] += src.get(k, 0)
        agg["total_tokens"] += src.get("total_tokens", 0)
    return {"usage": agg, "partial": partial}


def _mainthread_cost(session_transcripts: list[str]) -> dict:
    agg = {k: 0 for k in _TOKEN_KEYS}
    agg["total_tokens"] = 0
    partial = False
    for sp in session_transcripts:
        p = Path(sp).expanduser()
        if not p.exists():
            partial = True
            continue
        u = usage.parse_trace_usage(p)
        for k in _TOKEN_KEYS:
            agg[k] += u[k]
        agg["total_tokens"] += u["total_tokens"]
    return {"usage": agg, "partial": partial}


def _wallclock_sec(events: list[dict]) -> float:
    """Sum dispatch -> outcome deltas, one dispatch per outcome.

    Events are append-only / chronological. A dispatch is retired the moment
    it is consumed by a matching outcome, so a later re-reap outcome for the
    same (rule, run) key — with no intervening fresh dispatch (the
    crash-mid-promote repair path and the pin/regrade path both produce this;
    kernel.py cmd_reap documents that re-reaping an already-outcome'd run is
    deliberately allowed) — finds no dispatch to pair with and contributes
    nothing, instead of re-matching the stale original dispatch.
    """
    dispatches = {}
    total = 0.0
    for e in events:
        key = (e.get("rule"), e.get("run"))
        if e.get("type") == "dispatch":
            dispatches[key] = e["ts"]
        elif e.get("type") == "outcome" and key in dispatches:
            total += (_parse_ts(e["ts"]) - _parse_ts(dispatches[key])).total_seconds()
            del dispatches[key]
    return total


def aggregate_run(run: dict, repo_root: Path) -> dict:
    module = run.get("module")
    events = _read_events(repo_root, module) if module else []
    task = (
        _task_cost(repo_root, module, events)
        if module
        else {
            "usage": {**{k: 0 for k in _TOKEN_KEYS}, "total_tokens": 0},
            "partial": False,
        }
    )
    main = _mainthread_cost(run.get("session_transcripts", []))
    row = {
        "arm": run.get("arm"),
        "design": run.get("design"),
        "seed": run.get("seed"),
        "module": module,
        "task_tokens": task["usage"]["total_tokens"],
        "mainthread_tokens": main["usage"]["total_tokens"],
        "total_tokens": task["usage"]["total_tokens"] + main["usage"]["total_tokens"],
        "wallclock_sec": _wallclock_sec(events) if module else 0.0,
        "cost_partial": task["partial"] or main["partial"],
        # quality columns joined later (workstream 3)
        "pass_at_1": None,
    }
    for k in _TOKEN_KEYS:
        row[k] = task["usage"][k] + main["usage"][k]
    return row


def run_manifest(manifest_path: Path, repo_root: Path) -> list[dict]:
    manifest = json.loads(Path(manifest_path).read_text())
    return [aggregate_run(r, repo_root) for r in manifest.get("runs", [])]


_CSV_COLUMNS = [
    "arm",
    "design",
    "seed",
    "module",
    "task_tokens",
    "mainthread_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "wallclock_sec",
    "cost_partial",
    "pass_at_1",
]


def write_outputs(rows: list[dict], out_prefix: Path) -> None:
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    out_prefix.with_suffix(".json").write_text(
        json.dumps({"runs": rows}, indent=2) + "\n"
    )
    with out_prefix.with_suffix(".csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in _CSV_COLUMNS})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="log -> cost metrics aggregator")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True, help="output path prefix (.json/.csv)")
    ap.add_argument("--repo-root", default=str(_HERE.parents[2]))
    args = ap.parse_args(argv)
    rows = run_manifest(Path(args.manifest), Path(args.repo_root))
    write_outputs(rows, Path(args.out))
    print(json.dumps({"runs": len(rows), "out": args.out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
