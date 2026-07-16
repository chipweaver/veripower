"""Log -> cost metrics aggregator (P0 workstream (4), component C3).

Reads a run manifest and, per full run, computes:
  task_tokens       — sum over Task-execution stage outcomes:
                      outcome.cost_tokens if present (kernel instrumentation),
                      else a re-scan of that run's .subagent_traces/ (covers
                      pre-instrumentation runs; usage.parse_trace_usage).
  mainthread_tokens — sum over the run's orchestrator session transcript(s)
                      (main-thread stages + orchestrator overhead). Either
                      manifest-supplied (session_transcripts, taken as-is)
                      or auto-derived: harvested from the sessionId recorded
                      inside the module's Task-stage subagent traces (that
                      id is the PARENT orchestrator session), located at
                      <claude_projects_dir>/<sessionId>.jsonl.
  total_tokens      — task_tokens + mainthread_tokens (no double count:
                      sidechain turns are not in the session transcript).
  wallclock_sec     — sum of (outcome.ts - matching dispatch.ts).

Cost is audit-only. Quality columns (pass@1 etc.) are left blank here and
joined later once the arm-blind adjudication harness (workstream (3)) lands.

CAVEAT — auto-derived mainthread is only trustworthy for a SINGLE clean
session (mainthread_clean=True). With more than one harvested session it
(a) misses any orchestrator session that dispatched no task stage, so that
session's main-thread cost is invisible to trace-harvesting, and (b)
over-counts if a session interleaved other modules or unrelated work
(session granularity != module granularity). mainthread_clean=False flags
this; the value is still a best-effort sum but must not be trusted. A
manifest-supplied transcript is treated as clean — the operator vouched
for it.

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


def _claude_projects_dir(repo_root: Path) -> Path:
    """Default location of this repo's Claude Code session transcripts:
    ~/.claude/projects/<encoded-repo-root>, where the encoding is the
    resolved repo-root path with "/" replaced by "-"."""
    encoded = str(Path(repo_root).resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded


def _session_ids_from_traces(
    repo_root: Path, module: str, events: list[dict]
) -> list[str]:
    """Harvest the parent orchestrator sessionId(s) recorded inside this
    module's Task-execution subagent traces. Dedup by (rule, run) — same
    rule as _task_cost (last outcome per key wins) — then read each run's
    .subagent_traces/*.output first line for its sessionId. Returns an
    ordered-unique list; never raises (missing dirs / unparseable lines /
    absent sessionId are skipped)."""
    latest: dict[tuple, dict] = {}
    for e in events:
        if e.get("type") != "outcome":
            continue
        rule = e.get("rule")
        r = rules.RULES.get(rule)
        if r is None or getattr(r, "execution", None) != "task":
            continue
        latest[(rule, e.get("run"))] = e

    seen: dict[str, None] = {}  # insertion-ordered set
    for (rule, run), _e in latest.items():
        tdir = (
            repo_root
            / "asic"
            / module
            / Path(*rules.workdir_root(rule))
            / "runs"
            / str(run)
            / ".subagent_traces"
        )
        if not tdir.is_dir():
            continue
        for f in sorted(tdir.glob("*.output")):
            try:
                first_line = f.read_text().splitlines()[0]
                rec = json.loads(first_line)
            except (OSError, ValueError, IndexError):
                continue
            if not isinstance(rec, dict):
                continue
            sid = rec.get("sessionId")
            if isinstance(sid, str) and sid:
                seen[sid] = None
    return list(seen)


def _task_cost(repo_root: Path, module: str, events: list[dict]) -> dict:
    """Sum Task-execution stage cost; per outcome prefer cost_tokens, else
    re-scan the trace. Returns {usage breakdown, partial}.

    Dedup by (rule, run): a second outcome for the same key with no
    intervening dispatch (crash-mid-promote repair, or a pin/regrade —
    kernel.py cmd_reap explicitly allows re-reaping an already-outcome'd
    run) is a REGRADE of that run, not a second run. Events are
    append-only / chronological, so the last outcome per key is the
    current one; only it is costed, matching _wallclock_sec's retirement
    of the matched dispatch for the same re-reap case.
    """
    agg = {k: 0 for k in _TOKEN_KEYS}
    agg["total_tokens"] = 0
    partial = False
    latest: dict[tuple, dict] = {}
    for e in events:
        if e.get("type") != "outcome":
            continue
        rule = e.get("rule")
        r = rules.RULES.get(rule)
        if r is None or getattr(r, "execution", None) != "task":
            continue  # main-thread cost lives in the session transcript
        latest[(rule, e.get("run"))] = e
    for e in latest.values():
        rule = e.get("rule")
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


def aggregate_run(
    run: dict, repo_root: Path, claude_projects_dir: Path | None = None
) -> dict:
    if claude_projects_dir is None:
        claude_projects_dir = _claude_projects_dir(repo_root)
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

    manifest_transcripts = run.get("session_transcripts")
    if manifest_transcripts:
        main = _mainthread_cost(manifest_transcripts)
        mainthread_source = "manifest"
        session_ids: list[str] = []
    elif module:
        # Auto-derive: harvest orchestrator sessionId(s) from this module's
        # Task-stage subagent traces. Trustworthy only for a single session
        # (see module docstring CAVEAT) — mainthread_clean flags the rest.
        session_ids = _session_ids_from_traces(repo_root, module, events)
        transcripts = [str(claude_projects_dir / f"{sid}.jsonl") for sid in session_ids]
        main = _mainthread_cost(transcripts)
        mainthread_source = "auto-from-traces"
    else:
        main = {
            "usage": {**{k: 0 for k in _TOKEN_KEYS}, "total_tokens": 0},
            "partial": False,
        }
        mainthread_source = "none"
        session_ids = []

    mainthread_clean = (mainthread_source == "manifest") or (len(session_ids) == 1)

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
        "session_ids": session_ids,
        "mainthread_source": mainthread_source,
        "mainthread_clean": mainthread_clean,
        # quality columns joined later (workstream 3)
        "pass_at_1": None,
    }
    for k in _TOKEN_KEYS:
        row[k] = task["usage"][k] + main["usage"][k]
    return row


def run_manifest(
    manifest_path: Path, repo_root: Path, claude_projects_dir: Path | None = None
) -> list[dict]:
    manifest = json.loads(Path(manifest_path).read_text())
    return [
        aggregate_run(r, repo_root, claude_projects_dir)
        for r in manifest.get("runs", [])
    ]


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
    "session_ids",
    "mainthread_source",
    "mainthread_clean",
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
            csv_row = dict(r)
            csv_row["session_ids"] = ";".join(r.get("session_ids") or [])
            w.writerow({k: csv_row.get(k) for k in _CSV_COLUMNS})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="log -> cost metrics aggregator")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True, help="output path prefix (.json/.csv)")
    ap.add_argument("--repo-root", default=str(_HERE.parents[2]))
    ap.add_argument(
        "--claude-projects-dir",
        default=None,
        help="override for ~/.claude/projects/<encoded-repo-root> "
        "(default: each run computes its own default from --repo-root)",
    )
    args = ap.parse_args(argv)
    claude_projects_dir = (
        Path(args.claude_projects_dir) if args.claude_projects_dir else None
    )
    rows = run_manifest(Path(args.manifest), Path(args.repo_root), claude_projects_dir)
    write_outputs(rows, Path(args.out))
    print(json.dumps({"runs": len(rows), "out": args.out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
