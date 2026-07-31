#!/usr/bin/env python3
"""rtl finalize — the lean rtl-design result.json.

Derives the envelope from the on-disk workdir: artifacts via partition.exit_artifacts, which
schema-validates both authored sidecars on the way (a malformed one is BLOCKED, never a silent
pass). Nothing here judges the intent reviews — not their content, their coverage, or their
presence; they reach canonical through artifacts[], and the kernel's own trust boundary is what
refuses to pin an oracle that matched nothing. A `status=fail` comes only from the caller's
--fail-reason: what this stage can derive from disk it can also repair by re-dispatching a
child. result.json is fully script-derived (run narration lives in events.jsonl). Exit 0 =
written (pass or fail); exit 2 = BLOCKED (internal raise).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from rtl._ledger import LedgerError
from rtl.partition import exit_artifacts, ledger_artifacts

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


def _reviews(workdir: Path) -> list:
    """Whatever the review wave landed, in artifacts[] shape. How the reviewers split the RTL
    between them — and so how many files they write — is theirs to decide, so this reads the
    directory instead of deriving names from the manifest roster. artifacts[] is the only route
    to canonical, and canonical is where the oracle selector looks, so every file found has to
    be listed there."""
    d = workdir / REVIEW_DIR
    if not d.is_dir():
        return []
    return [{"path": f"{REVIEW_DIR}/{p.name}"} for p in sorted(d.glob("*.md"))]


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

    artifacts = exit_artifacts(manifest, workdir) + _reviews(workdir)
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
