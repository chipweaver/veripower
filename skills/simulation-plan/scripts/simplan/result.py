import datetime
import json
import re
import sys
from pathlib import Path

from simplan._md import extract_section
from simplan.classify import input_digest, products_digest
from simplan.review import gate_verdict

STAGE = "simulation-plan"

_REJECT_REASON = "user rejected plan"
_WAIVED_CLASSIFICATIONS = {"false-positive", "accepted-risk"}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts) -> dict:
    return {
        "schema_version": 1,
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


def _record_input_digest(ss: dict, workdir: Path) -> None:
    """Record the declared-input digest for the next run's classify-delta freeze
    check; silently skipped if the inputs aren't readable (safe no-freeze fallback).
    The parents[3] climb assumes the canonical asic/<module>/Verification/
    simulation-plan/runs/<N> layout — verified by name before recording, so an
    off-layout workdir can never hash a coincidental wrong directory into the
    freeze baseline (it just skips, and the next classify-delta says proceed)."""
    try:
        parts = workdir.resolve().parents
        if (
            parts[0].name != "runs"
            or parts[1].name != "simulation-plan"
            or parts[2].name != "Verification"
        ):
            return
        ss["input_digest"] = input_digest(parts[3] / "Design" / "specification")
    except (OSError, IndexError):
        pass


def count_features(plan_md: str) -> int:
    """feature_count = distinct F-NN feature IDs referenced in the §3 Testpoints Table
    section (0 when the section is absent). Deliberately NOT a whole-document scan: a §5
    revision note citing a dropped F-NN must not inflate the count across reworks — the
    number means "features the current testpoints trace to". The \\b boundary + \\d+
    excludes a bare 'F-' and 'Frame-01'."""
    section = extract_section(plan_md, r"(^|.*)§?\s*3\.?\s*.*Testpoints")
    return len(set(re.findall(r"\bF-\d+\b", section)))


def enumerate_artifacts(workdir) -> list:
    """Fixed simulation-plan artifact set, present-only, with kinds (plan-review.json promotes
    per SKILL Step 4). Never lists result.json (self) — the envelope schema forbids it."""
    workdir = Path(workdir)
    fixed = [
        ("verification-plan.md", "plan"),
        ("scaffold-specification.json", "scaffold"),
        ("plan-review.json", "plan-review"),
    ]
    return [{"path": p, "kind": k} for p, k in fixed if (workdir / p).is_file()]


def build_result(workdir, module, *, waived, status, revision, fail_reason=None) -> int:
    """Assemble the lean simulation-plan result.json from the workdir.

    pass path: re-derives the counts (scaffold arrays + distinct-F-NN in the plan md §3)
    and the plan-adequacy gate verdict (gate_verdict over the on-disk plan-review.json)
    in-process, enforces the Step-5 approve precondition (a tripped-and-unwaived gate
    downgrades to a written status=fail), then records the freeze digests (input_digest
    + products_digest over the promoted artifact set).

    fail path (user reject, or an early-fail exit carrying fail_reason): NEVER reads the
    plan/scaffold — an early-fail workdir may hold neither, and a raise here would turn
    a routable fail into a BLOCKED. plan_adequacy_gate is included iff plan-review.json
    is PRESENT — an absent record is the legitimate early-fail-before-Step-4 case, but a
    present-and-corrupt record raises (finalize → exit 2), so corruption surfaces instead
    of silently dropping the flagged/waiver record from the promoted fail. artifacts[]
    stays the present-only enumeration, so a seeded rework workdir carries the full prior
    product set and a promoted fail cannot GC canonical down to a hollow view.

    The human-gate state (waived / status=user-reject / revision) is passed in by the
    caller, NOT derivable from any artifact.
    Returns 0 (result.json written, pass or fail). A raise -> finalize() exit 2 (BLOCKED)."""
    workdir = Path(workdir)

    if status == "fail":
        ss = {"fail_reason": fail_reason or _REJECT_REASON}
        if (workdir / "plan-review.json").is_file():
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

    scaffold = json.loads(
        (workdir / "scaffold-specification.json").read_text(encoding="utf-8")
    )
    plan_md = (workdir / "verification-plan.md").read_text(encoding="utf-8")
    review = json.loads((workdir / "plan-review.json").read_text(encoding="utf-8"))

    gate = gate_verdict(review)
    if waived:
        gate = {**gate, "waived": waived}
    # Approve precondition (SKILL.md §Step 5): pass iff gate clears OR every flagged is
    # waived. Waiver pairing keys on (tp_id, lens) and ignores location, matching the
    # SKILL's own gate granularity — intentional, not a defect.
    flagged_ids = {(f.get("tp_id"), f.get("lens")) for f in gate.get("flagged", [])}
    waived_ids = {(w.get("tp_id"), w.get("lens")) for w in (waived or [])}
    gate_ok = gate["gate"] == "clear" or flagged_ids <= waived_ids

    if gate_ok:
        ss = {
            "feature_count": count_features(plan_md),
            "testpoint_count": len(scaffold.get("testpoints", [])),
            "power_scenario_count": len(scaffold.get("power_scenarios", [])),
            "scaffold_summary": {
                "agent_count": len(scaffold.get("agents", [])),
                "sequence_count": len(scaffold.get("sequences", [])),
                "test_count": len(scaffold.get("tests", [])),
            },
            "plan_adequacy_gate": gate,
        }
        _record_input_digest(ss, workdir)
        artifacts = enumerate_artifacts(workdir)
        # The freeze check's second half: bind this pass's exact product bytes, so a
        # later classify-delta can prove "the canonical products are still what the
        # human approved" before the freeze branch skips the reviewer and the user loop.
        ss["products_digest"] = products_digest(workdir, [a["path"] for a in artifacts])
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
            "[simplan finalize] ERROR: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    try:
        waived = json.loads(waived_json) if waived_json else None
    except json.JSONDecodeError as exc:
        print(
            f"[simplan finalize] ERROR: --waived not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 2
    if waived is not None:
        err = _waived_error(waived)
        if err:
            print(f"[simplan finalize] ERROR: {err}", file=sys.stderr)
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
        print(f"[simplan finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
