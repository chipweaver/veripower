import datetime
import json
import math
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from spec.constraints import derive_constraints
from spec.coverage import verdict as coverage_verdict
from spec.coverage import violated_keys

STAGE = "specification"

_PPA_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent / "references" / "ppa.schema.json"
)
_REJECT_REASON = "design.md gate rejected at human review"


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
    print(f"[spec finalize] wrote {workdir / 'result.json'} (status={env['status']})")


def _write_ppa_json(workdir: Path, ppa_targets: list) -> None:
    """The stable PPA-targets sidecar synthesis/power-analysis read directly — same
    atomic temp+rename as result.json. Written only on an explicit --ppa-targets
    override; otherwise the Wave-1-authored disk copy IS the source and stays untouched."""
    tmp = workdir / "ppa.json.tmp"
    tmp.write_text(json.dumps(ppa_targets, indent=2) + "\n")
    tmp.replace(workdir / "ppa.json")


def _validate_ppa(targets) -> str | None:
    """Validate a ppa_targets array against ppa.schema.json. Returns a one-line defect
    description, or None when valid.

    This is the ONLY place ppa.json is ever validated. The kernel schema-gates result.json
    at reap, never this sidecar, and both downstream readers fail OPEN on a bad entry:
    synthesis filters an unrecognized dim away, and power-analysis skips a target whose
    scenario_id does not string-match. A miss here is therefore silent all the way down,
    which is why the schema is loaded rather than restated in Python.

    Two obligations the schema cannot carry, kept explicit on top of it:
      * `json.loads` accepts the NaN / Infinity tokens and `type: number` admits them, but
        they are not RFC-8259 JSON, and a NaN target makes power-analysis' `actual > target`
        false for every input, silently disarming that gate.
      * an unreadable schema must fail closed, never wave the targets through.
    """
    try:
        schema = json.loads(_PPA_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"{_PPA_SCHEMA.name} unreadable: {exc}"
    errors = sorted(
        Draft202012Validator(schema).iter_errors(targets),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        err = errors[0]
        path = "$" + "".join(
            f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path
        )
        return f"schema violation at {path}: {err.message}"
    for i, t in enumerate(targets):
        if isinstance(t["target"], float) and not math.isfinite(t["target"]):
            return f"ppa_targets[{i}].target must be finite (got {t['target']!r})"
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


def enumerate_artifacts(workdir: Path, top: str) -> list[dict]:
    """Fixed specification artifact set, present-only. NEVER lists brainstorm.md
    (module-root, outside the workdir — would break promote()) or result.json (self)."""
    workdir = Path(workdir)
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    fixed = [
        "design.md",
        "manifest.json",
        "spec-review/decisions.md",
        f"constraints/{top}.sdc",
        f"constraints/{top}.sgdc",
        "ppa.json",
        "clocks.json",
        "features.json",
        "top-io.json",
        "interconnects.json",
    ]
    child_docs = [c["doc"] for c in manifest.get("children", []) if c.get("doc")]
    child_hints = [
        f"check-hints/{c['name']}.json"
        for c in manifest.get("children", [])
        if c.get("name")
    ]
    child_reviews = [
        f"spec-review/{c['name']}.md"
        for c in manifest.get("children", [])
        if c.get("name")
    ]
    return [
        {"path": p}
        for p in fixed + child_docs + child_hints + child_reviews
        if (workdir / p).is_file()
    ]


def build_result(workdir, module, ppa_targets, status, fail_reason=None) -> int:
    """Assemble the lean specification result.json.

    pass path, in order: re-run check-coverage in-process (every one of its checks is a
    set operation over the workdir's own files, so a clean Step-5 verdict stays true
    unless an artifact was edited after the gate — a fail here is that edit, and BLOCKs)
    → re-run derive_constraints() in-process: the promoted SDC/SGDC are finalize's own
    regeneration from the current clocks.json + top-io.json (authoritative; Step 5 already
    generated them clean from the same source, so this BLOCKs only on an illegitimate
    post-Step-5 edit) → validate the ppa.json sidecar (a --ppa-targets override writes it;
    otherwise the Wave-1-authored {workdir}/ppa.json is re-validated in place, the PPA SSoT
    never copied into the envelope) → enumerate artifacts[], write the envelope.

    The semantic review is NOT re-judged here. Its findings and the user's per-finding
    resolutions are prose under spec-review/, promoted and fingerprinted as this stage's
    proposed oracle; a script re-reducing them to a verdict would only be checking a record
    against the same agent's own --status, and pin/signoff is where that endorsement is
    actually held to account.

    fail path (human reject, or an early-fail exit carrying fail_reason): NEVER runs
    the derivation — an early-fail's tables may be incomplete, and the derivation's
    fail-loud sys.exit would turn a routable fail into a BLOCKED. <TOP> comes straight
    from manifest.module. artifacts[] stays the present-only enumeration, so a seeded
    rework workdir carries the full prior product set and a promoted fail cannot GC
    canonical down to a hollow view.

    Returns 0 (result.json written, pass or fail). A raise -> finalize exit 2 (BLOCKED)."""
    workdir = Path(workdir)

    if status == "fail":
        top = _top_from_manifest(workdir)
        ss = {"top_module": top, "fail_reason": fail_reason or _REJECT_REASON}
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

    cov = coverage_verdict(workdir)
    if cov["status"] == "fail":
        raise ValueError(
            "check-coverage no longer passes at finalize: "
            f"{', '.join(violated_keys(cov))}. Step 5 left it clean, so an artifact was "
            "edited after the gate — re-run check-coverage and repair, do not finalize."
        )

    info = derive_constraints(
        workdir
    )  # reuse: resolves <TOP> + regenerates SDC/SGDC + self-checks
    top = info["top"]  # == manifest.module (the single <TOP> source)

    if ppa_targets is not None:
        err = _validate_ppa(ppa_targets)
        if err:
            raise ValueError(f"--ppa-targets override: {err}")
        _write_ppa_json(workdir, ppa_targets)
    else:
        # validate the Wave-1 ppa.json in place (raises -> BLOCKED); it is the PPA SSoT
        # synthesis/power-analysis read directly, not copied into this envelope.
        _load_ppa_from_disk(workdir)

    ss = {"top_module": top}
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
    fail_reason=None,
) -> int:
    """Parse the human-gate outcome args, then build_result. --ppa-targets is an optional
    override — by default the Wave-1-authored {workdir}/ppa.json is read from disk. exit
    0 = result.json written (pass or fail); exit 2 = BLOCKED (bad --ppa-targets JSON, empty
    --fail-reason, missing/invalid ppa.json, unreadable manifest, a derivation fail-loud, or
    any internal raise) — never conflated with status=fail."""
    if fail_reason is not None and not fail_reason.strip():
        print(
            "[spec finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    try:
        ppa = json.loads(ppa_targets_json) if ppa_targets_json is not None else None
    except json.JSONDecodeError as exc:
        print(
            f"[spec finalize] BLOCKED: --ppa-targets not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 2
    try:
        return build_result(workdir, module, ppa, status, fail_reason=fail_reason)
    except SystemExit as exc:
        # derive_constraints' fail-loud sys.exit is a BaseException; keep the
        # documented exit-code contract (2 = BLOCKED) instead of leaking exit 1.
        print(f"[spec finalize] BLOCKED: {exc.code or exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[spec finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
