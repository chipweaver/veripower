#!/usr/bin/env python3
"""lintcdc.result — assemble the lean lint-cdc result.json envelope.

Why a combiner and not one host tool: the gate engine `collect_report.py` is
`templates/`-deployed (run by `make lint` / `make cdc`, never invoked by the agent by
path) and runs ONCE PER KIND, each writing its own `*-violations.json`. So this module is
a pure file-reader over those two sidecars: it neither imports nor subprocesses the
parser, and writes no sidecar of its own.

The gate ANDs the two: status=pass iff both sidecars exist and neither counts an
error- or warning-severity message. `reason` on each violation row is derived from the
parser's tool `message`, which is faithful rather than a judgment, because the gate is the
COUNT and never the reason text.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from lintcdc import requirements

STAGE = "lint-cdc"


GATED = ("error", "warning")


def gated_violations(doc: dict) -> list[dict]:
    """Reshape the gate-counted rows to the schema's {id, rule, severity, reason} (+
    file/line/message kept as additionalProperties). Gated rows only, so this is empty
    on every pass: the full all-severity account stays in the promoted sidecar."""
    out = []
    for v in (doc or {}).get("violations", []):
        if v.get("severity") not in GATED:
            continue
        msg = v.get("message", "")
        out.append(
            {
                "id": v["id"],
                "rule": v["rule"],
                "severity": v["severity"],
                "reason": f"{v['rule']}: {msg}" if msg else v["rule"],
                "file": v.get("file"),
                "line": v.get("line"),
                "message": v.get("message"),
            }
        )
    return out


def gate_fail_reason(lint, cdc) -> str:
    # Both gate-fail shapes: a sidecar the parser never wrote, and gated rows in one it
    # did. Only reached when the caller passed no --fail-reason, so the wording stays
    # generic on purpose: whoever watched `make` fail knows more than this, and saying it
    # is their job.
    if lint is None:
        return "lint report missing/unparseable, not real sign-off"
    if cdc is None:
        return "CDC report missing/unparseable, not real sign-off"
    bits = []
    for kind, doc in (("lint", lint), ("CDC", cdc)):
        counts = (doc or {}).get("counts") or {}
        for sev in GATED:
            n = counts.get(sev) or 0
            if n:
                bits.append(f"{n} {kind} {sev}(s)")
    return "gated violations: " + ", ".join(bits)


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------

VERSION_RE = re.compile(r"SpyGlass Version\s*:\s*SpyGlass_(\S+)")


def enumerate_artifacts(workdir: Path) -> list[dict]:
    workdir = Path(workdir)
    excluded = {
        "result.json",
        "result.json.tmp",
        "dispatch.json",
        "runs",
        "spyglass_work",
    }
    return [
        {"path": p.name} for p in sorted(workdir.iterdir()) if p.name not in excluded
    ]


def finalize(workdir, rows, declared, fix_owner=None, fail_reason=None) -> int:
    """Assess the stage and write its result. Input or I/O errors leave no current result."""
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if fail_reason is not None and (not fail_reason.strip()):
        print(
            "[lintcdc finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2

    def _write_result(*, status, stage_specific, artifacts):
        result = {
            "stage": STAGE,
            "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": status,
            "artifacts": artifacts,
            "stage_specific": stage_specific,
        }
        result_path = Path(workdir) / "result.json"
        temporary_path = result_path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(result, indent=2) + "\n")
        temporary_path.replace(result_path)
        print(f"[lintcdc finalize] Written: {result_path} (status={status})")
        return 0

    try:
        workdir = Path(workdir)
        lint_path = workdir / "lint-violations.json"
        cdc_path = workdir / "cdc-violations.json"
        lint = json.loads(lint_path.read_text()) if lint_path.is_file() else None
        cdc = json.loads(cdc_path.read_text()) if cdc_path.is_file() else None
        report_path = workdir / "lint-report.txt"
        report_text = (
            report_path.read_text(errors="replace") if report_path.is_file() else ""
        )
        version_match = VERSION_RE.search(report_text)
        tool = (
            f"SpyGlass {version_match.group(1)}"
            if version_match
            else "SpyGlass unknown"
        )
        artifacts = enumerate_artifacts(workdir)
        lint_bad = (
            sum(lint["counts"][severity] for severity in GATED)
            if lint is not None
            else 0
        )
        cdc_bad = (
            sum(cdc["counts"][severity] for severity in GATED) if cdc is not None else 0
        )
        violations = gated_violations(lint) + gated_violations(cdc)
        if fail_reason or lint is None or cdc is None or lint_bad or cdc_bad:
            stage_specific: dict = {
                "tool": tool,
                "fail_reason": fail_reason or gate_fail_reason(lint, cdc),
            }
            if violations:
                stage_specific["violations"] = violations
            if fix_owner:
                stage_specific["fix_owner"] = fix_owner
            return _write_result(
                status="fail", stage_specific=stage_specific, artifacts=artifacts
            )
        judged = requirements.merge(rows, [], declared)
        unmet = [entry["id"] for entry in judged if not entry["met"]]
        stage_specific = {
            "tool": tool,
            "violations": violations,
            "requirements": judged,
        }
        if unmet:
            stage_specific["fail_reason"] = (
                f"requirement(s) not met: {', '.join(unmet)}"
            )
            if fix_owner:
                stage_specific["fix_owner"] = fix_owner
        return _write_result(
            status="fail" if unmet else "pass",
            stage_specific=stage_specific,
            artifacts=artifacts,
        )
    except (OSError, ValueError) as exc:
        print(f"[lintcdc finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
