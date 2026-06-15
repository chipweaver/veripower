#!/usr/bin/env python3
"""simulation stage exit self-check (one pass at sim end). Mirrors validate_scaffold.py.

Checks, against the produced workdir + scaffold-specification.json + defaults.yaml:
  thin-D1  materialization defense: every sequences[]/agents[] SV file present; no TODO residue
           (any form -- a completed TB carries zero "TODO"; canonical templates carry none).
  D5       coverage extractable: structural-coverage.json present with an aggregate block.
  D6       coverage gate: each defaults.yaml.coverage_thresholds dim >= threshold
           (a dim whose measured value is null/absent -- e.g. a DUT with no FSM -- is skipped).

Exit non-zero with a readable, fix-oriented message on any failure (status truth = exit code,
NOT agent narration). Prints a one-line JSON verdict on stdout that the agent copies into
result.json stage_specific (additionalProperties): no new schema, no result.json write here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# Policy: ANY "TODO" in a materialized TB == unfinished work -> fail (a completed TB carries
# zero "TODO" anywhere). Match the bare word so no stub format escapes the gate. This REQUIRES
# the canonical templates to carry no non-marker "TODO" prose (base_seq.sv uses NOTE; the
# scaffold provenance headers avoid "TODO"), so the only "TODO" left in a *generated* file is
# an UNFILLED fill marker (TODO(sequence)/TODO(rm)/
# the no-seq test's "TODO: Start sequences here." ...), which is exactly what we want to fail on.
_TODO_RE = re.compile(r"TODO")


def _load_thresholds(path: Path) -> dict:
    """Read the coverage_thresholds block from defaults.yaml (dim -> float)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: float(v) for k, v in (data.get("coverage_thresholds") or {}).items()}


def thin_d1(workdir: Path, scaffold: dict) -> list[str]:
    """Materialization defense: required SV files present + no TODO residue (any form). Most
    files are guaranteed by derive_scaffold; this catches agent-side deletion/overwrite + any
    unfilled stub. Canonical templates carry zero non-marker TODO prose, so a match
    here is always a real unfilled marker."""
    module = scaffold.get("module", "")
    errs: list[str] = []
    for seq in scaffold.get("sequences", []):
        f = workdir / "tb/uvm/seq" / f"{module}_{seq.get('name')}_seq.sv"
        if not f.is_file():
            errs.append(
                f"missing sequence file {f.relative_to(workdir)} "
                f"(derive_scaffold generates it; was it deleted/overwritten?)"
            )
    for ag in scaffold.get("agents", []):
        name = ag.get("name")
        need = [f"{module}_{name}_monitor.sv", f"{module}_{name}_agent.sv"]
        if ag.get("mode") == "active":
            need.append(f"{module}_{name}_driver.sv")
        for fn in need:
            f = workdir / "tb/uvm/agent" / fn
            if not f.is_file():
                errs.append(f"missing agent file {f.relative_to(workdir)}")
    tb = workdir / "tb" / "uvm"
    if tb.is_dir():
        for sv in sorted(set(tb.rglob("*.sv")) | set(tb.rglob("*.svh"))):
            if _TODO_RE.search(sv.read_text(encoding="utf-8", errors="ignore")):
                errs.append(
                    f"TODO residue in {sv.relative_to(workdir)} "
                    f"(fill the scaffold; no TODO may survive in a completed TB)"
                )
    return errs


def coverage_gate(cov: dict | None, thresholds: dict) -> tuple[list[str], dict]:
    """D5 (extractable) + D6 (dims >= threshold; null dim skipped). Returns (errors, dims_report)."""
    if (
        cov is None
        or not isinstance(cov.get("aggregate"), dict)
        or not cov["aggregate"]
    ):
        return (
            [
                "coverage not extractable: structural-coverage.json missing or empty "
                "(urg did not produce a parseable report; cannot gate -> fail, never claim met)"
            ],
            {},
        )
    agg = cov["aggregate"]
    errs: list[str] = []
    dims: dict = {}
    for dim, thr in thresholds.items():
        if (
            dim not in agg
        ):  # urg never measured this dim -> cannot gate it -> fail (not silent skip)
            dims[dim] = {"value": "absent", "threshold": thr, "pass": False}
            errs.append(
                f"{dim} threshold configured but absent from the coverage report "
                f"(urg did not measure it; cannot gate)"
            )
            continue
        val = agg[dim]
        if (
            val is None
        ):  # measured as N/A ('--', e.g. a DUT with no FSM) -> skip, do not fail
            dims[dim] = {"value": None, "threshold": thr, "pass": True, "skipped": True}
            continue
        ok = val >= thr
        dims[dim] = {"value": val, "threshold": thr, "pass": ok}
        if not ok:
            errs.append(f"{dim} coverage {val} < threshold {thr}")
    return errs, dims


def main() -> int:
    p = argparse.ArgumentParser(
        description="simulation exit self-check (thin-D1 + D5 + D6)."
    )
    p.add_argument(
        "--workdir",
        required=True,
        help="sim workdir (contains tb/uvm + structural-coverage.json)",
    )
    p.add_argument("--scaffold", required=True, help="scaffold-specification.json path")
    p.add_argument(
        "--thresholds",
        help="defaults.yaml path (coverage_thresholds); required unless --thin-only",
    )
    p.add_argument(
        "--thin-only",
        action="store_true",
        help="env-exit gate: run thin-D1 (materialization) only -- skip coverage/D5/D6; "
        "--thresholds not required. Emits a trimmed {unmaterialized, todo_residue} verdict.",
    )
    args = p.parse_args()
    if not args.thin_only and not args.thresholds:
        p.error("--thresholds is required unless --thin-only is set")

    workdir = Path(args.workdir).resolve()
    scaffold = json.loads(Path(args.scaffold).read_text(encoding="utf-8"))

    d1_errs = thin_d1(workdir, scaffold)

    if args.thin_only:
        # env-exit gate: materialization only. No coverage, no result.json write -- the
        # env subagent gates its own STATUS: DONE on this exit code; finalize's full run
        # remains the authoritative result.json verdict. thin-D1 fail -> failure_phase=compile
        # (the existing mapping; this presence gate does not itself route conformance).
        verdict = {
            "unmaterialized": [e for e in d1_errs if "missing" in e],
            "todo_residue": [e for e in d1_errs if "TODO" in e],
        }
        if d1_errs:
            print(json.dumps(verdict))
            sys.exit(
                "validate_sim_exit --thin-only: materialization incomplete:\n  - "
                + "\n  - ".join(d1_errs)
                + "\nFill the scaffold (no TODO may survive; all required files present), "
                "then re-run. Budget-exhausted-with-residue -> failure_phase=compile."
            )
        print(
            "validate_sim_exit --thin-only: OK (thin-D1 clean -- materialization complete)"
        )
        print(json.dumps(verdict))
        return 0

    thresholds = _load_thresholds(Path(args.thresholds))
    cov_path = workdir / "structural-coverage.json"
    cov = (
        json.loads(cov_path.read_text(encoding="utf-8")) if cov_path.is_file() else None
    )
    cov_errs, dims = coverage_gate(cov, thresholds)
    errs = d1_errs + cov_errs

    verdict = {
        "coverage_extractable": cov is not None and bool(cov.get("aggregate")),
        "dims": dims,
        "unmaterialized": [e for e in d1_errs if "missing" in e],
        "todo_residue": [e for e in d1_errs if "TODO" in e],
    }
    if errs:
        print(json.dumps(verdict))
        sys.exit(
            "validate_sim_exit: simulation exit checks failed:\n  - "
            + "\n  - ".join(errs)
            + "\nThin-D1 fails -> failure_phase=compile; coverage fails -> failure_phase=coverage. "
            "Fix the TB / stimulus and re-run (status truth is this gate, not narration)."
        )
    print(
        "validate_sim_exit: OK (thin-D1 clean, coverage extractable, all gated dims >= threshold)"
    )
    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
