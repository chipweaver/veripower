import datetime
import json
import sys
from pathlib import Path

from spec.classify import input_digest
from spec.constraints import derive_constraints
from spec.review import gate_verdict

STAGE = "specification"


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
    tmp.replace(
        workdir / "result.json"
    )  # atomic: never observed half-written (kernel §5.1)
    sys.stdout.write(
        f"[spec finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _write_ppa_json(workdir: Path, ppa_targets: list) -> None:
    """The stable PPA-targets sidecar synthesis/power-analysis read directly
    (spec §4.3) — same atomic temp+rename as result.json (kernel §5.1)."""
    tmp = workdir / "ppa.json.tmp"
    tmp.write_text(json.dumps(ppa_targets, indent=2) + "\n")
    tmp.replace(workdir / "ppa.json")


def _record_input_digest(ss: dict, workdir: Path) -> None:
    """Record the declared-input digest for the next run's classify-delta freeze
    check; silently skipped if the input isn't readable (safe no-freeze fallback)."""
    try:
        ss["input_digest"] = input_digest(workdir.parents[3] / "brainstorm.md")
    except (OSError, IndexError):
        pass


def compute_spec_gate(workdir: Path, waived: list) -> dict:
    """Re-derive the Step-7 gate verdict in-process from the on-disk spec-review.json
    (already schema-gated when Step 7 wrote it -> call the pure fold, not the CLI),
    then merge the human waiver classification relayed via --waived."""
    doc = json.loads((Path(workdir) / "spec-review.json").read_text(encoding="utf-8"))
    g = gate_verdict(doc)
    g["waived"] = waived
    return g


def enumerate_artifacts(workdir: Path, top: str) -> list[dict]:
    """Fixed specification artifact set, present-only, with kinds. NEVER lists brainstorm.md
    (module-root, outside the workdir — would break promote()) or result.json (self)."""
    workdir = Path(workdir)
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    fixed = [
        ("design.md", "design"),
        ("manifest.json", "manifest"),
        ("coverage.json", "coverage"),
        ("spec-review.json", "spec-review"),
        (f"constraints/{top}.sdc", "sdc"),
        (f"constraints/{top}.sgdc", "sgdc"),
        ("ppa.json", "ppa"),
    ]
    child_docs = [
        (c["doc"], "child-design") for c in manifest.get("children", []) if c.get("doc")
    ]
    return [
        {"path": p, "kind": k} for p, k in fixed + child_docs if (workdir / p).is_file()
    ]


def build_result(workdir, module, ppa_targets, waived, status) -> int:
    """Assemble the lean specification result.json. Re-runs derive_constraints() in-process
    (so <TOP> + the constraint files cannot diverge), re-derives spec_gate from the on-disk
    spec-review.json, enforces the approve precondition, enumerates artifacts[], writes the
    envelope. Returns 0 (result.json written, pass or fail). A raise -> main() exit 2 (BLOCKED).

    Agent γ-floor inputs (correction A): ppa_targets (D6 brainstorm), waived (the human waiver
    classification recorded at the Step-8 gate), status (the user's approve/reject). The gate
    verdict itself is re-derived, NOT agent-supplied."""
    workdir = Path(workdir)
    info = derive_constraints(
        workdir
    )  # reuse: resolves <TOP> + regenerates SDC/SGDC + self-checks
    top = info["top"]  # == manifest.module (the single <TOP> source)

    spec_gate = compute_spec_gate(workdir, waived)
    # Owner-decided granularity: waiver pairing keys on (child, lens) and ignores location,
    # matching the SKILL's own gate granularity (SKILL.md:269) — intentional, not a defect.
    waived_keys = {(w.get("child"), w.get("lens")) for w in waived}
    unresolved = [
        f
        for f in spec_gate["flagged"]
        if (f.get("child"), f.get("lens")) not in waived_keys
    ]

    # Approve precondition (SKILL.md:269): a pass is honored only when the gate is clear OR
    # every flagged finding is waived. Never ship an unreviewed/unwaived pass.
    if status == "pass" and unresolved:
        ss = {
            "top_module": top,
            "fail_reason": "approve precondition unmet: flagged spec-review findings neither cleared nor waived",
            "spec_gate": spec_gate,
        }
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=enumerate_artifacts(workdir, top),
            ),
        )
        return 0

    if status == "pass":
        _write_ppa_json(workdir, ppa_targets)
        ss = {"top_module": top, "ppa_targets": ppa_targets, "spec_gate": spec_gate}
        _record_input_digest(ss, workdir)
    else:
        ss = {
            "top_module": top,
            "fail_reason": "design.md gate rejected at human review",
            "spec_gate": spec_gate,
        }
    _write_result(
        workdir,
        _envelope(
            module,
            status=status,
            stage_specific=ss,
            artifacts=enumerate_artifacts(workdir, top),
        ),
    )
    return 0


def finalize(workdir, module, *, status, ppa_targets_json, waived_json) -> int:
    """Parse the γ-floor JSON args, then build_result. exit 0 = result.json written
    (pass or fail); exit 2 = BLOCKED (bad --ppa-targets/--waived JSON, or any internal
    raise) — never conflated with status=fail."""
    try:
        ppa = json.loads(ppa_targets_json)
        waived = json.loads(waived_json)
    except json.JSONDecodeError as exc:
        print(
            f"[spec finalize] ERROR: --ppa-targets/--waived not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 2
    try:
        return build_result(workdir, module, ppa, waived, status)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[spec finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
