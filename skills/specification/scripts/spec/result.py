import datetime
import json
import math
import sys
from pathlib import Path

from spec.constraints import derive_constraints
from spec.review import gate_verdict

STAGE = "specification"

_PPA_DIMS = {"area_um2", "timing_slack_ns", "power_mw"}
_REJECT_REASON = "design.md gate rejected at human review"


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
        f"[spec finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _write_ppa_json(workdir: Path, ppa_targets: list) -> None:
    """The stable PPA-targets sidecar synthesis/power-analysis read directly — same
    atomic temp+rename as result.json. Written only on an explicit --ppa-targets
    override; otherwise the Wave-1-authored disk copy IS the source and stays untouched."""
    tmp = workdir / "ppa.json.tmp"
    tmp.write_text(json.dumps(ppa_targets, indent=2) + "\n")
    tmp.replace(workdir / "ppa.json")


def _validate_ppa(targets) -> str | None:
    """Shape-check a ppa_targets array (mirrors result.schema.json's ppa_targets items:
    dim in the PPA enum, finite numeric target). Returns a one-line defect description,
    or None when valid — checked at finalize so a bad wave-1 ppa.json (or a bad
    override) blocks here with a fix-oriented message instead of failing schema
    validation later at reap. Non-finite floats are rejected explicitly: Python's
    json.loads accepts NaN/Infinity tokens, but they are not valid RFC-8259 JSON and
    would corrupt the ppa.json SSoT for strict downstream parsers."""
    if not isinstance(targets, list):
        return f"ppa_targets must be a JSON array (got {type(targets).__name__})"
    for i, t in enumerate(targets):
        if not isinstance(t, dict):
            return f"ppa_targets[{i}] must be an object"
        if t.get("dim") not in _PPA_DIMS:
            return (
                f"ppa_targets[{i}].dim must be one of {sorted(_PPA_DIMS)} "
                f"(got {t.get('dim')!r})"
            )
        target = t.get("target")
        if isinstance(target, bool) or not isinstance(target, (int, float)):
            return f"ppa_targets[{i}].target must be a number (got {target!r})"
        if isinstance(target, float) and not math.isfinite(target):
            return f"ppa_targets[{i}].target must be finite (got {target!r})"
    return None


def _load_ppa_from_disk(workdir: Path) -> list:
    """Read the Wave-1-authored `{workdir}/ppa.json` — the PPA SSoT synthesis /
    power-analysis bind to as their acceptance standard. Raises ValueError (finalize →
    exit 2 BLOCKED) when absent or malformed: wave-1 must emit it (D6 ppa_targets
    verbatim; [] when no PPA), or the caller passes --ppa-targets to override."""
    p = Path(workdir) / "ppa.json"
    try:
        targets = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(
            f"{p} missing: Wave 1 must emit ppa.json (D6 ppa_targets verbatim; "
            "[] when none) — or pass --ppa-targets to override"
        ) from None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{p} unreadable / not JSON: {exc}") from None
    err = _validate_ppa(targets)
    if err:
        raise ValueError(f"{p}: {err}")
    return targets


def _top_from_manifest(workdir: Path) -> str:
    """<TOP> = manifest.module — the same source derive_constraints pins; read directly
    on the fail path (which never runs the derivation). A missing/unreadable manifest
    raises → finalize exits 2 (BLOCKED): with no manifest there is no artifact set to
    enumerate, and a blocked run never promotes, so canonical cannot be GC'd against a
    hollow view."""
    manifest = json.loads((Path(workdir) / "manifest.json").read_text(encoding="utf-8"))
    top = manifest.get("module")
    if not top:
        raise ValueError("manifest.json missing 'module' (the <TOP> name)")
    return top


def compute_spec_gate(workdir: Path, waived: list) -> dict:
    """Re-derive the Step-7 gate verdict in-process from the on-disk spec-review.json
    (already schema-gated when Step 7 wrote it -> call the pure fold, not the CLI),
    then merge the human waiver classification relayed via --waived."""
    # Read as-is: review-vs-content freshness is a process invariant — the skill re-runs its
    # gate on the current design.md before finalize (SKILL.md "Re-entry and completion"), not enforced here.
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


def build_result(workdir, module, ppa_targets, waived, status, fail_reason=None) -> int:
    """Assemble the lean specification result.json.

    pass path, in order: re-run derive_constraints() in-process (so <TOP> + the
    constraint files cannot diverge) → re-derive spec_gate from the on-disk
    spec-review.json and enforce the approve precondition (an unmet precondition
    downgrades to a written status=fail BEFORE any ppa handling, so a ppa fault can
    never preempt the documented downgrade) → resolve ppa_targets (an explicit
    override wins and lands on disk; otherwise the Wave-1-authored {workdir}/ppa.json
    is read) → enumerate artifacts[], write the envelope.

    fail path (human reject, or an early-fail exit carrying fail_reason): NEVER runs
    the derivation — an early-fail's tables may be incomplete, and the derivation's
    fail-loud sys.exit would turn a routable fail into a BLOCKED. <TOP> comes straight
    from manifest.module. spec_gate is included iff spec-review.json is PRESENT — an
    absent record is the legitimate early-fail-before-Step-7 case, but a
    present-and-corrupt record raises (finalize → exit 2), so corruption surfaces
    instead of silently dropping the flagged/waiver record from the promoted fail.
    artifacts[] stays the present-only enumeration, so a seeded rework workdir carries
    the full prior product set and a promoted fail cannot GC canonical down to a
    hollow view.

    Returns 0 (result.json written, pass or fail). A raise -> finalize exit 2 (BLOCKED)."""
    workdir = Path(workdir)

    if status == "fail":
        top = _top_from_manifest(workdir)
        ss = {"top_module": top, "fail_reason": fail_reason or _REJECT_REASON}
        if (workdir / "spec-review.json").is_file():
            ss["spec_gate"] = compute_spec_gate(workdir, waived)
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

    info = derive_constraints(
        workdir
    )  # reuse: resolves <TOP> + regenerates SDC/SGDC + self-checks
    top = info["top"]  # == manifest.module (the single <TOP> source)

    spec_gate = compute_spec_gate(workdir, waived)
    # Waiver pairing keys on (child, lens) and ignores location, matching the SKILL's own
    # gate granularity (SKILL.md §Step 7, waiver pairing rule) — intentional, not a defect.
    waived_keys = {(w.get("child"), w.get("lens")) for w in waived}
    unresolved = [
        f
        for f in spec_gate["flagged"]
        if (f.get("child"), f.get("lens")) not in waived_keys
    ]

    # Approve precondition (SKILL.md §Step 8, approve precondition): a pass is honored
    # only when the gate is clear OR every flagged finding is waived. Never ship an
    # unreviewed/unwaived pass. Checked before ppa resolution so the downgrade is
    # unconditional.
    if unresolved:
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

    override = ppa_targets is not None
    if override:
        err = _validate_ppa(ppa_targets)
        if err:
            raise ValueError(f"--ppa-targets override: {err}")
        _write_ppa_json(workdir, ppa_targets)
    else:
        ppa_targets = _load_ppa_from_disk(workdir)

    ss = {"top_module": top, "ppa_targets": ppa_targets, "spec_gate": spec_gate}
    artifacts = enumerate_artifacts(workdir, top)
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


def finalize(
    workdir,
    module,
    *,
    status,
    ppa_targets_json=None,
    waived_json="[]",
    fail_reason=None,
) -> int:
    """Parse the human-gate outcome args, then build_result. --ppa-targets is an optional
    override — by default the Wave-1-authored {workdir}/ppa.json is read from disk. exit
    0 = result.json written (pass or fail); exit 2 = BLOCKED (bad --ppa-targets/--waived
    JSON, empty --fail-reason, missing/invalid ppa.json, unreadable manifest, a
    derivation fail-loud, or any internal raise) — never conflated with status=fail."""
    if fail_reason is not None and not fail_reason.strip():
        print(
            "[spec finalize] ERROR: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    try:
        ppa = json.loads(ppa_targets_json) if ppa_targets_json is not None else None
        waived = json.loads(waived_json)
    except json.JSONDecodeError as exc:
        print(
            f"[spec finalize] ERROR: --ppa-targets/--waived not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 2
    try:
        return build_result(
            workdir, module, ppa, waived, status, fail_reason=fail_reason
        )
    except SystemExit as exc:
        # derive_constraints' fail-loud sys.exit is a BaseException; keep the
        # documented exit-code contract (2 = BLOCKED) instead of leaking exit 1.
        print(f"[spec finalize] FAIL=internal {exc.code or exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[spec finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
