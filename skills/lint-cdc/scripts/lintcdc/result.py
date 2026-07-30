#!/usr/bin/env python3
"""lintcdc.result — assemble the lean lint-cdc result.json envelope.

Why a combiner and not one host tool: the gate engine `collect_report.py` is
`templates/`-deployed (run by `make lint` / `make cdc`, never invoked by the agent by
path) and runs ONCE PER KIND, each writing its own `*-violations.json`. So this module is
a pure file-reader over those two sidecars: it neither imports nor subprocesses the
parser, and writes no sidecar of its own.

The gate ANDs the two: status=pass iff both sidecars exist and counts.error == 0 in both.
`reason` on each violation row is derived from the parser's tool `message`, which is
faithful rather than a judgment, because the gate is the error COUNT and never the reason
text.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

STAGE = "lint-cdc"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts) -> dict:
    return {
        "stage": STAGE,
        "module": module,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": artifacts,
        "stage_specific": stage_specific,
    }


def _write(workdir: Path, env: dict) -> None:
    tmp = workdir / "result.json.tmp"
    tmp.write_text(json.dumps(env, indent=2) + "\n")
    tmp.replace(workdir / "result.json")  # atomic: never observed half-written
    sys.stdout.write(
        f"[lintcdc finalize] Written: {workdir / 'result.json'}"
        f" (status={env['status']})\n"
    )


def _load_violations(path: Path):
    """Return the collect_report.py JSON, or None if absent (write-fresh-or-nothing unlinks
    it on a parser fail, so absence == that kind did not produce a clean report)."""
    return json.loads(path.read_text()) if path.is_file() else None


def _error_violations(doc: dict) -> list[dict]:
    """Reshape the error-severity rows to the schema's {id, rule, severity, reason} (+
    file/line/message kept as additionalProperties). Error rows only, so this is empty
    on every pass: the full all-severity account stays in the promoted sidecar."""
    out = []
    for v in (doc or {}).get("violations", []):
        if v.get("severity") != "error":
            continue
        msg = v.get("message", "")
        out.append(
            {
                "id": v["id"],
                "rule": v["rule"],
                "severity": "error",
                "reason": f"{v['rule']}: {msg}" if msg else v["rule"],
                "file": v.get("file"),
                "line": v.get("line"),
                "message": v.get("message"),
            }
        )
    return out


def run(workdir, module, *, fix_owner=None, fail_reason=None) -> int:
    workdir = Path(workdir)
    lint = _load_violations(workdir / "lint-violations.json")
    cdc = _load_violations(workdir / "cdc-violations.json")
    tool = parse_tool(workdir)
    artifacts = enumerate_artifacts(workdir)

    # AND gate: both *-violations.json present (== both make runs reached collect_report
    # cleanly) AND counts.error == 0 in both. A missing file means that kind's make did
    # not produce a clean report, which is a fail on its own.
    lint_err = (lint or {}).get("counts", {}).get("error")
    cdc_err = (cdc or {}).get("counts", {}).get("error")
    violations = _error_violations(lint) + _error_violations(cdc)
    if fail_reason or lint is None or cdc is None or lint_err or cdc_err:
        # A caller-supplied reason wins: it comes from the agent that watched `make`
        # fail and read the parser's stderr, which is strictly more than this verb can
        # reconstruct from a report that is not on disk.
        ss: dict = {
            "tool": tool,
            "fail_reason": fail_reason
            or _gate_fail_reason(lint, cdc, lint_err, cdc_err),
        }
        for key, doc in (("lint_counts", lint), ("cdc_counts", cdc)):
            if doc is not None:
                ss[key] = doc["counts"]
        if violations:
            # violations[] IS the failure account: every row carries rule + file:line +
            # reason. A summary field derived from it would restate it one key away, and a
            # rule prefix cannot answer the question that is NOT in it — whose artifact must
            # change. That answer is fix_owner, which the agent names.
            ss["violations"] = violations
        if fix_owner:
            ss["fix_owner"] = fix_owner
        _write(
            workdir,
            _envelope(module, status="fail", stage_specific=ss, artifacts=artifacts),
        )
        return 0
    ss = {
        "tool": tool,
        "lint_counts": lint["counts"],
        "cdc_counts": cdc["counts"],
        "violations": violations,
    }
    _write(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


def _gate_fail_reason(lint, cdc, lint_err, cdc_err) -> str:
    # Both gate-fail shapes: a sidecar the parser never wrote, and error rows in one it
    # did. Only reached when the caller passed no --fail-reason, so the wording stays
    # generic on purpose: whoever watched `make` fail knows more than this, and saying it
    # is their job.
    if lint is None:
        return "lint report missing/unparseable, not real sign-off"
    if cdc is None:
        return "CDC report missing/unparseable, not real sign-off"
    bits = []
    if lint_err:
        bits.append(f"{lint_err} lint error(s)")
    if cdc_err:
        bits.append(f"{cdc_err} CDC error(s)")
    return "error-severity violations: " + ", ".join(bits)


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"SpyGlass Version\s*:\s*SpyGlass_(\S+)")


def parse_tool(workdir: Path) -> str:
    """The ruleset version the report itself states. This stage's oracle IS the SpyGlass
    ruleset, and the kernel's reap-time identity record scrapes only the library env vars,
    so the envelope is the one place the ruleset that produced the proof is written down."""
    rpt = Path(workdir) / "lint-report.txt"
    if rpt.is_file():
        m = _VERSION_RE.search(rpt.read_text(errors="replace"))
        if m:
            return (
                f"SpyGlass {m.group(1)}"  # SpyGlass_vL-2016.06 -> SpyGlass vL-2016.06
            )
    return "SpyGlass unknown"


def enumerate_artifacts(workdir: Path) -> list[dict]:
    workdir = Path(workdir)
    candidates = [
        "scripts/constraints.sgdc",  # the warm-start anchor the next round inherits
        "lint-report.txt",
        "cdc-report.txt",
        "lint-violations.json",
        "cdc-violations.json",
        "scripts/waiver.tcl",
    ]
    # envelope.schema forbids listing result.json itself; excluded by construction.
    # A *-violations.json the parser did not emit is simply absent (write-fresh-or-nothing
    # unlinked it) and therefore not listed.
    return [{"path": p} for p in candidates if (workdir / p).is_file()]


def finalize(workdir, module, fix_owner=None, fail_reason=None) -> int:
    """Assemble the lean lint-cdc result.json from the two *-violations.json + headers.
    exit 0 = result.json written (status pass or fail); exit 2 = BLOCKED (an empty
    --fail-reason, or any internal raise) — never conflated with status=fail."""
    if fail_reason is not None and not fail_reason.strip():
        print(
            "[lintcdc finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    try:
        return run(workdir, module, fix_owner=fix_owner, fail_reason=fail_reason)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[lintcdc finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
