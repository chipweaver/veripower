import datetime
import json
import sys
from pathlib import Path

from simplan._plan import SIDECAR_NAMES
from simplan.review import gate_verdict

STAGE = "simulation-plan"

_REJECT_REASON = "user rejected plan"
_WAIVED_CLASSIFICATIONS = {"false-positive", "accepted-risk"}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts) -> dict:
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
        f"[simplan finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def enumerate_artifacts(workdir) -> list:
    """Fixed simulation-plan artifact set, present-only, with kinds (plan-review.json promotes
    per the SKILL plan-adequacy review). Never lists result.json (self) — the envelope schema forbids it."""
    workdir = Path(workdir)
    fixed = ["verification-plan.md", *SIDECAR_NAMES, "plan-review.json"]
    return [{"path": p} for p in fixed if (workdir / p).is_file()]


def build_result(workdir, module, *, waived, status, revision, fail_reason=None) -> int:
    """Assemble the lean simulation-plan result.json from the workdir.

    pass path: re-derives the plan-adequacy gate verdict (gate_verdict over the on-disk
    plan-review.json) in-process, and enforces the approve precondition (a tripped-and-unwaived
    gate downgrades to a written status=fail). It carries no scaffold-array counts: they were
    re-derivable from the scaffold spec and read by nobody.

    fail path (user reject, or an early-fail exit carrying fail_reason): NEVER reads the
    plan-review record — an early-fail workdir may hold none, and a raise here would turn
    a routable fail into a BLOCKED. plan_adequacy_gate is included iff plan-review.json
    is PRESENT — an absent record is the legitimate early-fail case (before the plan-adequacy review), but a
    present-and-corrupt record raises (finalize → exit 2), so corruption surfaces instead
    of silently dropping the flagged/waiver record from the promoted fail. artifacts[]
    stays the present-only enumeration, so a seeded rework workdir carries the full prior
    product set and a promoted fail cannot GC canonical down to a hollow view.

    The human-gate state (waived / status=user-reject / revision) is passed in by the
    caller, NOT derivable from any artifact.
    Returns 0 (result.json written, pass or fail). A raise -> finalize() exit 2 (BLOCKED)."""
    workdir = Path(workdir)

    if status == "fail":
        review_present = (workdir / "plan-review.json").is_file()
        if fail_reason is None and not review_present:
            # A user reject can only follow the plan-adequacy review and user loop — the judged record must be on
            # disk. A bare --status fail on a workdir that never ran the gate would
            # fabricate a human rejection; force the caller to say what failed.
            raise ValueError(
                "--status fail without --fail-reason is the user reject and "
                "requires plan-review.json on disk; for an early fail pass --fail-reason"
            )
        if waived and not review_present:
            # A waiver is a human trust record attached to a judged gate; with no
            # plan-review.json there is no gate to attach it to — dropping it
            # silently would lose the operator's classifications for the rework.
            raise ValueError(
                "--waived supplied but no plan-review.json on disk to attach it to"
            )
        ss = {"fail_reason": fail_reason or _REJECT_REASON}
        if review_present:
            review = json.loads(
                (workdir / "plan-review.json").read_text(encoding="utf-8")
            )
            gate = gate_verdict(review)
            if waived:
                gate = {**gate, "waived": waived}
            ss["plan_adequacy_gate"] = gate
        if revision:
            ss["revision"] = revision
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=enumerate_artifacts(workdir),
            ),
        )
        return 0

    # Read as-is: review-vs-content freshness is a process invariant — the skill re-runs its
    # gate on the current plan before finalize (SKILL.md "Re-entry and completion"), not enforced here.
    review = json.loads((workdir / "plan-review.json").read_text(encoding="utf-8"))

    gate = gate_verdict(review)
    if waived:
        gate = {**gate, "waived": waived}
    # Approve precondition (SKILL.md, user review loop): pass iff gate clears OR every flagged is
    # waived. Waiver pairing keys on (tp_id, lens) and ignores location, matching the
    # SKILL's own gate granularity — intentional, not a defect.
    flagged_ids = {(f.get("tp_id"), f.get("lens")) for f in gate.get("flagged", [])}
    waived_ids = {(w.get("tp_id"), w.get("lens")) for w in (waived or [])}
    gate_ok = gate["gate"] == "clear" or flagged_ids <= waived_ids

    if gate_ok:
        ss = {
            "plan_adequacy_gate": gate,
        }
        artifacts = enumerate_artifacts(workdir)
    else:
        ss = {
            "fail_reason": "plan-adequacy gate tripped (see plan-review.json)",
            "plan_adequacy_gate": gate,
        }
        artifacts = enumerate_artifacts(workdir)
    if revision:
        ss["revision"] = revision
    _write_result(
        workdir,
        _envelope(
            module,
            status="pass" if gate_ok else "fail",
            stage_specific=ss,
            artifacts=artifacts,
        ),
    )
    return 0


def _waived_error(waived) -> str | None:
    """Validate the parsed --waived array: each entry is a human waiver record and must
    carry a non-empty tp_id/lens/reason and a known classification. A placeholder or
    truncated entry is rejected loud — the waiver is a human-authored trust record, and
    finalize must not launder an empty one into the promoted gate."""
    if not isinstance(waived, list):
        return f"--waived must be a JSON array, got {type(waived).__name__}"
    for i, w in enumerate(waived):
        if not isinstance(w, dict):
            return f"--waived[{i}] must be an object, got {type(w).__name__}"
        for key in ("tp_id", "lens", "reason"):
            v = w.get(key)
            if not isinstance(v, str) or not v.strip():
                return f"--waived[{i}] missing non-empty {key!r}"
        if w.get("classification") not in _WAIVED_CLASSIFICATIONS:
            return (
                f"--waived[{i}] classification {w.get('classification')!r} not in "
                f"{sorted(_WAIVED_CLASSIFICATIONS)}"
            )
    return None


def finalize(
    workdir, module, *, waived_json, status, revision, fail_reason=None
) -> int:
    """Parse the human-gate outcome args, then build_result. exit 0 = result.json written
    (pass or fail); exit 2 = BLOCKED (bad --waived JSON/content, empty --fail-reason, or
    any internal raise) — never conflated with status=fail."""
    if fail_reason is not None and not fail_reason.strip():
        print(
            "[simplan finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    if fail_reason is not None and status != "fail":
        # An unpaired --fail-reason is a caller slip about to invert a failure into a
        # computed pass; refuse loudly instead of silently discarding the reason.
        print(
            "[simplan finalize] BLOCKED: --fail-reason requires --status fail",
            file=sys.stderr,
        )
        return 2
    try:
        waived = json.loads(waived_json) if waived_json else None
    except json.JSONDecodeError as exc:
        print(
            f"[simplan finalize] BLOCKED: --waived not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 2
    if waived is not None:
        err = _waived_error(waived)
        if err:
            print(f"[simplan finalize] BLOCKED: {err}", file=sys.stderr)
            return 2
    try:
        return build_result(
            workdir,
            module,
            waived=waived,
            status=status,
            revision=revision,
            fail_reason=fail_reason,
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[simplan finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
