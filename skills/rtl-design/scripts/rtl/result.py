#!/usr/bin/env python3
"""rtl finalize — the lean rtl-design result.json.

Derives the envelope from the on-disk workdir: status / fail_reason / artifacts via
partition.post_verdict, which schema-validates both authored sidecars on the way (a malformed
one is BLOCKED, never a silent pass). No verdict is reduced from the intent reviews.
result.json is fully script-derived (run narration lives in events.jsonl). Exit 0 = written
(pass or fail); exit 2 = BLOCKED (internal raise).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from rtl._ledger import LedgerError
from rtl.partition import ledger_artifacts, post_verdict

STAGE = "rtl-design"
REVIEW_DIR = "semantic-review"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts, fix_owner=None) -> dict:
    """fix_owner rides on a failure only, and only when the caller named one: its ABSENCE is
    what decide reads as "this stage cannot tell", so it must never serialize empty."""
    if status == "fail" and fix_owner:
        stage_specific = {**stage_specific, "fix_owner": fix_owner}
    return {
        "stage": STAGE,
        "module": module,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": artifacts,
        "stage_specific": stage_specific,
    }


def _write_result(workdir: Path, env: dict) -> None:
    tmp = workdir / "result.json.tmp"
    tmp.write_text(json.dumps(env, indent=2) + "\n")
    tmp.replace(workdir / "result.json")  # atomic: never observed half-written
    sys.stdout.write(
        f"[rtl finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _exit_verdict(workdir: Path, manifest: Path) -> dict:
    """Re-derive the exit verdict IN-PROCESS over the on-disk state: {status, fail_reason?,
    artifacts[]}. post_verdict schema-validates both authored sidecars on the way, so a
    hand-authored shape defect is BLOCKED here rather than promoted."""
    return post_verdict(manifest, workdir)[0]


def _reviews(workdir: Path) -> list:
    """Whatever the review wave landed, in artifacts[] shape. How the reviewers split the RTL
    between them — and so how many files they write — is theirs to decide, so this reads the
    directory instead of deriving names from the manifest roster. artifacts[] is the only route
    to canonical, so every file found has to be listed there."""
    d = workdir / REVIEW_DIR
    if not d.is_dir():
        return []
    return [{"path": f"{REVIEW_DIR}/{p.name}"} for p in sorted(d.glob("*.md"))]


def _require_reviews(workdir: Path) -> list:
    """A passing envelope needs the intent review to have happened at all. Nothing else in this
    stage checks that it did — there is no in-stage human gate here, unlike specification's — so
    a silently skipped wave would otherwise ship as a clean pass. Coverage is not counted and no
    review is reduced to a verdict: both are the stage's judgment to act on."""
    found = _reviews(workdir)
    if not found:
        raise ValueError(
            f"no intent review under {REVIEW_DIR}/ — the RTL cannot pass unreviewed"
        )
    return found


def _caller_reported_artifacts(workdir: Path) -> list:
    """artifacts[] for a caller-reported failure, whose whole premise is that the on-disk state
    cannot yield a verdict. A fail envelope promotes exactly like a passing one and promote
    treats artifacts[] as the new canonical view, so enumerate whatever the sidecars still hold
    rather than drop a readable prior baseline. Unreadable sidecars yield [], all that is knowable.
    """
    try:
        files = ledger_artifacts(workdir)
    except LedgerError:
        files = []
    return files + _reviews(workdir)


def build_result(workdir, module, manifest, fail_reason=None, fix_owner=None) -> int:
    """Build the lean rtl-design result.json from the on-disk workdir. The caller supplies
    only what no on-disk state can express: `fail_reason` for an early exit, and `fix_owner` for
    the rule that must act on a failure. Returns 0 (result.json written, pass or fail); a raise
    → exit 2 (BLOCKED)."""
    workdir, manifest = Path(workdir), Path(manifest)

    if fail_reason:
        # An early exit outside the derivable set: a child could not deliver, or a sidecar is
        # malformed, so no verdict can be re-derived. Record the caller's one-line reason.
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific={"fail_reason": fail_reason},
                artifacts=_caller_reported_artifacts(workdir),
                fix_owner=fix_owner,
            ),
        )
        return 0

    exit_v = _exit_verdict(workdir, manifest)
    artifacts = list(exit_v.get("artifacts", []))

    if exit_v.get("status") != "pass":
        # topology fail — verbatim verdict, plus whatever review already landed.
        ss = {"fail_reason": exit_v.get("fail_reason", "rtl exit gate failed")}
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=artifacts + _reviews(workdir),
                fix_owner=fix_owner,
            ),
        )
        return 0

    artifacts += _require_reviews(workdir)
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific={}, artifacts=artifacts),
    )
    return 0


def finalize(workdir, module, manifest, fail_reason=None, fix_owner=None) -> int:
    """Build the lean rtl-design result.json from the on-disk workdir.
    exit 0 = result.json written (status pass or fail); exit 2 = BLOCKED (any internal
    raise) — never conflated with status=fail. (Owns the policy the deleted main() had.)"""
    try:
        return build_result(
            workdir, module, manifest, fail_reason=fail_reason, fix_owner=fix_owner
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[rtl finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
