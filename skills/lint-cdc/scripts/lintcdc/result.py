#!/usr/bin/env python3
"""lintcdc.result — assemble the lean lint-cdc result.json envelope.

The ONE new module in the skill-elegance cure (cure-spec §3.1 explicit exception):
lint-cdc's gate engine `collect_report.py` is `templates/`-deployed (run by `make lint`
/ `make cdc`, never invoked by the agent by path) and runs ONCE PER KIND, each writing
its own `*-violations.json`. There is no single host tool to grow, so this thin combiner
ANDs the two already-written sidecars and writes the envelope. Model: frontend-signoff signoff/result.py
(a pure file-reader that hand-writes the envelope).

Pure file-reader: it does NOT import or subprocess collect_report.py and writes ZERO new
sidecar. It reads the two collect_report.py outputs (lint-violations.json /
cdc-violations.json) already on disk for the AND gate (status=pass iff counts.error == 0 in
BOTH) + the counts, parses the slim reproducibility header (top_module / tool) from the
report, reshapes the error-severity violations, enumerates artifacts[], and hand-writes the
envelope dict (no shared build_envelope helper — user decision F1).

No agent input: lint-cdc is pure-deterministic (no human gate). The schema-required per-error
`reason` is DERIVED from the parser's tool `message` (`reason = "<rule>: <message>"`). The gate
is the error COUNT (`counts.error == 0`), so `reason` is purely descriptive — deriving it from
the tool message is faithful, not a judgment. Field set per the field-necessity verdict (Task 0).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

STAGE = "lint-cdc"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _write(workdir: Path, env: dict) -> None:
    (workdir / "result.json").write_text(json.dumps(env, indent=2) + "\n")
    sys.stdout.write(
        f"[lintcdc finalize] Written: {workdir / 'result.json'}"
        f" (status={env['status']})\n"
    )


def _load_violations(path: Path):
    """Return the collect_report.py JSON, or None if absent (write-fresh-or-nothing unlinks
    it on a parser fail, so absence == that kind did not produce a clean report)."""
    return json.loads(path.read_text()) if path.is_file() else None


def _error_violations(doc: dict) -> list[dict]:
    """Reshape the error-severity rows to the schema's {id, rule, severity, reason} (+
    file/line/message kept as additionalProperties). `reason` is derived from the tool
    message (gate is the error count, not the reason text — so this is descriptive, not
    a judgment)."""
    out = []
    for v in (doc or {}).get("violations", []):
        if v.get("severity") != "error":
            continue
        msg = v.get("message", "")
        out.append(
            {
                "id": v["id"],
                "rule": v["rule"],
                "severity": "error",
                "reason": f"{v['rule']}: {msg}" if msg else v["rule"],
                "file": v.get("file"),
                "line": v.get("line"),
                "message": v.get("message"),
            }
        )
    return out


def run(workdir, module, *, top) -> int:
    workdir = Path(workdir)
    lint = _load_violations(workdir / "lint-violations.json")
    cdc = _load_violations(workdir / "cdc-violations.json")
    tool = parse_tool(workdir)
    top_module = top or read_top(workdir)
    artifacts = enumerate_artifacts(workdir)

    # AND gate: both *-violations.json present (== both make runs reached collect_report
    # cleanly) AND counts.error == 0 in both. A missing file == that kind's make did not
    # produce a clean report (early-fail path; the agent already wrote that envelope in
    # Steps 4/5 — see main()).
    lint_err = (lint or {}).get("counts", {}).get("error")
    cdc_err = (cdc or {}).get("counts", {}).get("error")
    violations = _error_violations(lint) + _error_violations(cdc)
    if lint is None or cdc is None or lint_err or cdc_err:
        ss: dict = {
            "top_module": top_module,
            "tool": tool,
            "fail_reason": _gate_fail_reason(lint, cdc, lint_err, cdc_err),
        }
        for key, doc in (("lint_counts", lint), ("cdc_counts", cdc)):
            if doc is not None:
                ss[key] = doc["counts"]
        if violations:
            ss["violations"] = violations
        _write(
            workdir,
            _envelope(module, status="fail", stage_specific=ss, artifacts=artifacts),
        )
        return 0
    ss = {
        "top_module": top_module,
        "tool": tool,
        "lint_counts": lint["counts"],
        "cdc_counts": cdc["counts"],
        "violations": violations,
    }
    _write(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


def _gate_fail_reason(lint, cdc, lint_err, cdc_err) -> str:
    # The COMBINER's own gate-fail surface: the error-count>0 case (both reports present)
    # + a defensive missing-file fallback. DISTINCT from the SKILL's early-fail
    # token->reason map (FAIL=missing/unparseable/count_mismatch, SKILL.md:101), which
    # stays skill-owned and fires FIRST on a real missing/unparseable report — so the two
    # reason vocabularies never collide (route.py treats fail_reason as a non-parsed hint).
    if lint is None:
        return "lint report missing/unparseable, not real sign-off"
    if cdc is None:
        return "CDC report missing/unparseable, not real sign-off"
    bits = []
    if lint_err:
        bits.append(f"{lint_err} lint error(s)")
    if cdc_err:
        bits.append(f"{cdc_err} CDC error(s)")
    return "error-severity violations: " + ", ".join(bits)


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"SpyGlass Version\s*:\s*SpyGlass_(\S+)")
_TOP_HDR_RE = re.compile(r"^top:\s*(\S+)", re.M)
_ENV_TOP_RE = re.compile(r'TOP="?\$\{TOP:-([A-Za-z_][A-Za-z0-9_]*)\}"?')


def parse_tool(workdir: Path) -> str:
    rpt = Path(workdir) / "lint-report.txt"
    if rpt.is_file():
        m = _VERSION_RE.search(rpt.read_text(errors="replace"))
        if m:
            return (
                f"SpyGlass {m.group(1)}"  # SpyGlass_vL-2016.06 -> SpyGlass vL-2016.06
            )
    return "SpyGlass unknown"


def read_top(workdir: Path):
    rpt = Path(workdir) / "lint-report.txt"
    if rpt.is_file():
        m = _TOP_HDR_RE.search(rpt.read_text(errors="replace"))
        if m and m.group(1) != "UNKNOWN":
            return m.group(1)
    env = Path(workdir) / "env.sh"
    if env.is_file():
        m = _ENV_TOP_RE.search(env.read_text(errors="replace"))
        if m:
            return m.group(1)
    return None


def enumerate_artifacts(workdir: Path) -> list[dict]:
    workdir = Path(workdir)
    candidates = [
        "scripts/constraints.sgdc",  # Iron Rule warm-start anchor: MUST be in artifacts[] on pass (promotion is pass-gated by the promote machinery, so a fail-path listing here is inert, not a leak)
        "lint-report.txt",
        "cdc-report.txt",
        "lint-violations.json",
        "cdc-violations.json",
        "scripts/waiver.tcl",
    ]
    # envelope.schema forbids listing result.json itself; excluded by construction.
    # On an early-fail a *-violations.json the parser did not emit is simply absent here
    # (write-fresh-or-nothing unlinked it) -> not listed, exactly per SKILL :120.
    return [{"path": p} for p in candidates if (workdir / p).is_file()]


def finalize(workdir, module, top) -> int:
    """Assemble the lean lint-cdc result.json from the two *-violations.json + headers.
    exit 0 = result.json written (status pass or fail); exit 2 = BLOCKED (any internal
    raise) — never conflated with status=fail. (Owns the policy the deleted main() had.)"""
    try:
        return run(workdir, module, top=top)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[lintcdc finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
