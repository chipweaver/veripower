#!/usr/bin/env python3
"""rtl-design exit gate: R-1 top-module coverage + child-status precedence.

Emits a one-line JSON verdict on stdout that the main thread copies verbatim into result.json:
  {"status": "pass|fail", "fail_reason"?: str, "artifacts": [{"path": str}, ...]}
`artifacts` is the envelope shape (array of {path} objects) — the framework promotes each
artifact by its path and schema-validates the envelope at stage completion; a flat string
list would break both.

Status truth = exit code (0 pass / 1 fail), NOT narration. On a gate-fail this script exits 1 with
the fail_reason inside the stdout verdict and EMPTY stderr by design — the verdict JSON is the single
source (the main thread reads status/fail_reason/artifacts from stdout, never stderr, for this script).
Does NOT schema-validate result.json — the framework does that at stage completion.

Usage:
  validate_rtl_exit.py --manifest <manifest.json> --top <top_module>
                       [--phase {pre,post}]
                       [--fresh <fresh_reports.json>] [--ledger <.child_reports.json>]
  --phase pre  : manifest+top only (no reports); for pre-dispatch fail-fast.
  --phase post : (default) also folds in blocked-child check + emits artifacts from ledger;
                 requires --fresh and --ledger.
Exit: 0 if status==pass, 1 if status==fail.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
from ledger_io import load_ledger  # noqa: E402
from validate_semantic_review import compute_gate  # noqa: E402  pure fn (Task 1.5)

STAGE = "rtl-design"


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _coverage_verdict(manifest: Path, top: str):
    """Coverage + purity over manifest+top (no reports). Returns (status, reason)."""
    children = _read_json(manifest).get("children", [])
    covering = [c for c in children if top in c.get("rtl_modules", [])]
    if len(covering) != 1:
        return "fail", (
            f"exit-check: top_module '{top}' covered by {len(covering)} children "
            f"(expected 1) — specification must emit exactly one top-integration child"
        )
    if covering[0].get("rtl_modules") != [top]:
        return "fail", (
            f"exit-check: top-integration child '{covering[0]['name']}' is not pure: "
            f"rtl_modules={covering[0].get('rtl_modules')} (expected ['{top}'] only) — "
            f"specification must not bundle logic modules with the top module"
        )
    return "pass", None


def post_verdict(manifest: Path, top: str, fresh: Path, ledger: Path):
    """The --phase post exit verdict: coverage+purity + blocked-child precedence + the
    artifacts[] enumeration from the ledger. Returns (verdict_dict, rc). The single copy of
    the gate both main() and build_result reuse — no behavior change, only factored out."""
    status, reason = _coverage_verdict(manifest, top)
    if not (fresh and ledger):
        return (
            {
                "status": "fail",
                "artifacts": [],
                "fail_reason": "validate_rtl_exit --phase post requires --fresh and --ledger",
            },
            1,
        )
    fresh_data = _read_json(fresh)
    ledger_data = load_ledger(ledger)
    if status == "pass":
        blocked = {
            n: r.get("reason", "")
            for n, r in fresh_data.items()
            if r.get("status") == "blocked"
        }
        if blocked:
            status = "fail"
            reason = "child blocked: " + "; ".join(
                f"{n}: {m}" for n, m in blocked.items()
            )

    files = sorted({f for rec in ledger_data.values() for f in rec["files"]})
    paths = files + ["filelist.txt", "README.md", ".child_reports.json"]
    # Envelope shape: artifacts MUST be an array of {"path": ...} objects (the framework promotes each
    # artifact by path + schema-validates the envelope); a flat string list would break both.
    artifacts = [{"path": p} for p in paths]
    verdict = {"status": status, "artifacts": artifacts}
    if reason:
        verdict["fail_reason"] = reason
    return verdict, (0 if status == "pass" else 1)


# ── finalize: assemble the lean result.json (v4 stage-CLI-tool) ──────────────
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
        f"[validate_rtl_exit] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _exit_verdict(workdir: Path, top: str, manifest: Path) -> dict:
    """Re-derive the --phase post verdict IN-PROCESS over the converged on-disk ledger:
    {status, fail_reason?, artifacts[]}. Calls the same post_verdict() the legacy CLI uses,
    so the topology/blocked-child gate + artifact enumeration are not duplicated."""
    return post_verdict(
        manifest, top, workdir / "fresh_reports.json", workdir / ".child_reports.json"
    )[0]


def _locus_fail_reason(gate: dict) -> str:
    """Mechanize the semantic-trip fail narrative: a spec-locus trip is named first, else rtl-local."""
    flagged = gate.get("flagged", [])
    loci = gate.get("loci", {})
    first = flagged[0]
    extra = f" (+{len(flagged) - 1} more)" if len(flagged) > 1 else ""
    if loci.get("spec"):
        return f"semantic gate: spec-rooted intent defect — {first['child']}{extra}"
    return f"semantic gate: rtl-local intent defect — {first['child']}{extra}"


def build_result(workdir, module, top, manifest) -> int:
    """Assemble the lean rtl-design result.json from the converged on-disk workdir.
    Re-derives the exit verdict in-process (status/fail_reason/artifacts, verbatim), then on a
    passing exit folds in the semantic gate via the pure compute_gate() (in-process, no subprocess,
    no schema-gate re-hit). A semantic gate=trip flips a passing exit to fail with a locus-tagged
    fail_reason. Adds top_module, drops the free-text note. result.json is fully script-derived —
    no agent input (run narration lives in events.jsonl). Returns 0 (result.json written, pass or
    fail). A raise → main() exit 2 (BLOCKED). Field set per the field-necessity verdict (Task 0)."""
    workdir, manifest = Path(workdir), Path(manifest)
    exit_v = _exit_verdict(workdir, top, manifest)
    artifacts = list(exit_v.get("artifacts", []))

    if exit_v.get("status") != "pass":
        # topology / blocked-child fail — verbatim verdict; the semantic gate was never reached.
        ss = {
            "top_module": top,
            "fail_reason": exit_v.get("fail_reason", "rtl exit gate failed"),
        }
        _write_result(
            workdir,
            _envelope(module, status="fail", stage_specific=ss, artifacts=artifacts),
        )
        return 0

    # exit verdict passed -> fold in the semantic gate via the pure fn (already-validated doc).
    review = json.loads((workdir / "semantic-review.json").read_text(encoding="utf-8"))
    gate = compute_gate(review)
    artifacts.append({"path": "semantic-review.json"})
    if gate.get("gate") == "trip":
        ss = {
            "top_module": top,
            "semantic_gate": gate,
            "fail_reason": _locus_fail_reason(gate),
        }
        _write_result(
            workdir,
            _envelope(module, status="fail", stage_specific=ss, artifacts=artifacts),
        )
        return 0
    ss = {"top_module": top, "semantic_gate": gate}
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


def _run_exit_gate_cli(args: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--top", required=True)
    ap.add_argument("--phase", choices=["pre", "post"], default="post")
    ap.add_argument("--fresh", type=Path)
    ap.add_argument("--ledger", type=Path)
    a = ap.parse_args(args)

    # --phase pre: coverage + purity only, from manifest+top (no reaped reports, nothing authored yet).
    if a.phase == "pre":
        status, reason = _coverage_verdict(a.manifest, a.top)
        verdict = {"status": status, "artifacts": []}
        if reason:
            verdict["fail_reason"] = reason
        print(json.dumps(verdict, ensure_ascii=False))
        return 0 if status == "pass" else 1

    # --phase post: also fold in the blocked-child precedence + emit artifacts from the ledger.
    verdict, rc = post_verdict(a.manifest, a.top, a.fresh, a.ledger)
    print(json.dumps(verdict, ensure_ascii=False))
    return rc


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) > 1 and argv[1] == "finalize":
        ap = argparse.ArgumentParser(
            prog="validate_rtl_exit.py finalize",
            description="Assemble the lean rtl-design result.json from the converged workdir.",
        )
        ap.add_argument("--workdir", required=True, type=Path)
        ap.add_argument("--module", required=True)
        ap.add_argument("--top", required=True, help="top module (= manifest.module)")
        ap.add_argument(
            "--manifest",
            required=True,
            type=Path,
            help="Design/specification/manifest.json",
        )
        try:
            a = ap.parse_args(argv[2:])
        except SystemExit as exc:
            if exc.code not in (0, None):
                print("[validate_rtl_exit] ERROR: usage", file=sys.stderr)
                return 2
            return 0
        try:
            return build_result(a.workdir, a.module, a.top, a.manifest)
        except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
            print(f"[validate_rtl_exit] FAIL=internal {exc}", file=sys.stderr)
            return 2
    # ── legacy exit-gate CLI (UNCHANGED behavior) ──────────────────────────────
    return _run_exit_gate_cli(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
