import datetime
import json
import re
import sys
from pathlib import Path

from simplan.review import gate_verdict

STAGE = "simulation-plan"


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
    (workdir / "result.json").write_text(json.dumps(env, indent=2) + "\n")
    sys.stdout.write(
        f"[simplan finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def count_features(plan_md: str) -> int:
    """feature_count = distinct F-NN feature IDs referenced anywhere in verification-plan.md
    (an informational whole-document scan, not a §3-only count — on a rework an F-NN cited only
    in a §5 revision note still counts). The \\b boundary + \\d+ excludes a bare 'F-' and 'Frame-01'."""
    return len(set(re.findall(r"\bF-\d+\b", plan_md)))


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


def build_result(workdir, module, *, waived, status, revision) -> int:
    """Assemble the lean simulation-plan result.json from the workdir.
    Re-derives the counts (scaffold arrays + distinct-F-NN in the plan md) and the
    plan-adequacy gate verdict (gate_verdict over the on-disk plan-review.json) in-process,
    then computes status. The human-gate state (waived / status=user-reject / revision) is
    gamma-floor: passed in by the caller, NOT derivable from any artifact.
    Returns 0 (result.json written, pass or fail). A raise -> finalize() exit 2 (BLOCKED)."""
    workdir = Path(workdir)
    scaffold = json.loads(
        (workdir / "scaffold-specification.json").read_text(encoding="utf-8")
    )
    plan_md = (workdir / "verification-plan.md").read_text(encoding="utf-8")
    review = json.loads((workdir / "plan-review.json").read_text(encoding="utf-8"))

    gate = gate_verdict(review)
    if waived:
        gate = {**gate, "waived": waived}
    # status: pass iff gate clears OR every flagged is waived; user-reject (--status fail) wins.
    flagged_ids = {(f.get("tp_id"), f.get("lens")) for f in gate.get("flagged", [])}
    waived_ids = {(w.get("tp_id"), w.get("lens")) for w in (waived or [])}
    gate_ok = gate["gate"] == "clear" or flagged_ids <= waived_ids
    computed = "pass" if gate_ok else "fail"
    final = "fail" if status == "fail" else computed

    if final == "pass":
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
    else:
        reason = (
            "user rejected plan"
            if status == "fail"
            else "plan-adequacy gate tripped (see plan-review.json)"
        )
        ss = {"fail_reason": reason, "plan_adequacy_gate": gate}
    if revision:
        ss["revision"] = revision
    _write_result(
        workdir,
        _envelope(
            module,
            status=final,
            stage_specific=ss,
            artifacts=enumerate_artifacts(workdir),
        ),
    )
    return 0


def finalize(workdir, module, *, waived_json, status, revision) -> int:
    """Parse the γ-floor --waived JSON, then build_result. exit 0 = result.json written
    (pass or fail); exit 2 = BLOCKED (bad --waived JSON, or any internal raise) — never
    conflated with status=fail."""
    try:
        waived = json.loads(waived_json) if waived_json else None
    except json.JSONDecodeError as exc:
        print(
            f"[simplan finalize] ERROR: --waived not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 2
    try:
        return build_result(
            workdir, module, waived=waived, status=status, revision=revision
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[simplan finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
