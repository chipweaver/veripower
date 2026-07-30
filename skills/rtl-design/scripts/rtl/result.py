#!/usr/bin/env python3
"""rtl finalize — assemble the lean rtl-design result.json (exit gate + folded semantic gate).

Re-derives the exit verdict in-process over the converged ledger (status / fail_reason /
artifacts, verbatim via partition.post_verdict), then on a passing exit folds in the
semantic gate via the pure review.compute_gate over a schema-validated oracle doc
(review.load_validated: in-process, no subprocess). A
semantic gate=trip flips a passing exit to fail with a locus-tagged fail_reason (spec-rooted
named first, else rtl-local). result.json is fully script-derived (run narration lives in
events.jsonl). Exit 0 = result.json written (pass or fail); exit 2 = BLOCKED (internal raise).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from rtl.partition import ledger_artifacts, post_verdict
from rtl.review import compute_gate, load_validated

STAGE = "rtl-design"


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


def _exit_verdict(workdir: Path, top: str, manifest: Path) -> dict:
    """Re-derive the **post exit-gate** verdict IN-PROCESS over the converged on-disk state:
    {status, fail_reason?, artifacts[]}. Calls the same post_verdict() the assemble verb uses,
    so the topology/blocked-child gate + artifact enumeration are not duplicated."""
    return post_verdict(manifest, top, workdir / "reaped-children.json", workdir)[0]


def _caller_reported_artifacts(workdir: Path) -> list:
    """artifacts[] for a caller-reported failure, whose whole premise is that the on-disk state
    cannot yield a verdict. A fail envelope promotes exactly like a passing one and promote
    treats artifacts[] as the new canonical view, so enumerate whatever the sidecars still hold
    rather than drop a readable prior baseline. Unreadable sidecars yield [], all that is knowable.
    """
    try:
        return ledger_artifacts(workdir)
    except Exception:  # noqa: BLE001 — any unreadable sidecar state
        return []


def _locus_fail_reason(gate: dict) -> str:
    """Mechanize the semantic-trip fail narrative: a spec-locus trip is named first, else rtl-local."""
    flagged = gate.get("flagged", [])
    loci = gate.get("loci", {})
    first = flagged[0]
    extra = f" (+{len(flagged) - 1} more)" if len(flagged) > 1 else ""
    if loci.get("spec"):
        return f"semantic gate: spec-rooted intent defect — {first['child']}{extra}"
    return f"semantic gate: rtl-local intent defect — {first['child']}{extra}"


def build_result(
    workdir, module, top, manifest, fail_reason=None, fix_owner=None
) -> int:
    """Assemble the lean rtl-design result.json from the converged on-disk workdir.
    Re-derives the exit verdict in-process (status/fail_reason/artifacts, verbatim), then on a
    passing exit schema-validates semantic-review.json and folds in the semantic gate via the pure
    compute_gate() (in-process, no subprocess). A semantic gate=trip flips a passing exit to fail with a locus-tagged
    fail_reason, drops the free-text note. Every verdict is script-derived; the caller supplies
    only `fail_reason`, for the early exits no on-disk state can express (run narration lives in
    events.jsonl). Returns 0 (result.json written, pass or fail). A raise → main() exit 2
    (BLOCKED)."""
    workdir, manifest = Path(workdir), Path(manifest)

    if fail_reason:
        # An early exit outside the derivable set: the reaped reports or the sidecars are
        # malformed, so no gate can be re-derived. Record the caller's one-line reason.
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

    exit_v = _exit_verdict(workdir, top, manifest)
    artifacts = list(exit_v.get("artifacts", []))

    if exit_v.get("status") != "pass":
        # topology / blocked-child fail — verbatim verdict; the semantic gate was never reached.
        ss = {"fail_reason": exit_v.get("fail_reason", "rtl exit gate failed")}
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=artifacts,
                fix_owner=fix_owner,
            ),
        )
        return 0

    # exit verdict passed -> fold in the semantic gate. load_validated is the backstop on the
    # oracle artifact itself: an unvalidated doc would reduce through compute_gate's .get()
    # defaults to gate=clear. A violation raises -> exit 2 (BLOCKED), never status=pass.
    # Freshness stays a process invariant: the skill re-runs its gate on the current RTL before
    # finalize (SKILL.md "Re-entry and completion"), not enforced here.
    review = load_validated(workdir / "semantic-review.json")
    gate = compute_gate(review)
    artifacts.append({"path": "semantic-review.json"})
    if gate.get("gate") == "trip":
        ss = {"semantic_gate": gate, "fail_reason": _locus_fail_reason(gate)}
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=artifacts,
                fix_owner=fix_owner,
            ),
        )
        return 0
    ss = {"semantic_gate": gate}
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


def finalize(workdir, module, top, manifest, fail_reason=None, fix_owner=None) -> int:
    """Assemble the lean rtl-design result.json from the converged workdir.
    exit 0 = result.json written (status pass or fail); exit 2 = BLOCKED (any internal
    raise) — never conflated with status=fail. (Owns the policy the deleted main() had.)"""
    try:
        return build_result(
            workdir, module, top, manifest, fail_reason=fail_reason, fix_owner=fix_owner
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[rtl finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
