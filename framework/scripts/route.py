#!/usr/bin/env python3
"""VeriPower deterministic rework-router.

Pure evaluator: maps a stage failure to a rework target, or to ESCALATE /
NEED_INPUT. Holds no state; the only I/O is optionally reading a result.json
passed by path. Most failures route on the closed-enum `failed_rule` /
`failure_kind`; lint-cdc instead routes by input-provenance — `failures[0]
.category` names which upstream input produced the failure (the SGDC seed vs.
the RTL), so a CDC failure can route to `specification` instead of always
blaming `rtl-design` (U4). Composed unchanged inside schedule.py; stays
stateless and remains the SINGLE home for the static failure->target maps —
no other file (SKILL.md / ARCHITECTURE.md / schemas) may restate them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ESCALATE = "ESCALATE"
NEED_INPUT = "NEED_INPUT"

# ── Routing policy: four pure enum->target maps ────────────────────

# power-analysis tooling failures, keyed by failures[0].category.
PA_CATEGORY: dict[str, str] = {
    "netlist": "synthesis",
    "sdf": "synthesis",
    "tb_uvm": "simulation",
    "gls_runtime": "simulation",
    "saif_dump": "simulation",
    "ptpx_data": "simulation",
    "plan": "simulation-plan",
    "tooling": ESCALATE,
}

# Stages whose failure always routes to one fixed ancestor.
FIXED_TARGET: dict[str, str] = {
    "simulation-plan": "specification",
}

# lint-cdc failures keyed by failures[0].category -> the input's producer (U4).
# sgdc_seed/constraint come from specification's derive-constraints; rtl_cdc/lint_rtl
# come from rtl-design's RTL. Only meaningful once F1 makes multi-clock CDC run.
LINT_CATEGORY: dict[str, str] = {
    "sgdc_seed": "specification",
    "constraint": "specification",
    "rtl_cdc": "rtl-design",
    "lint_rtl": "rtl-design",
    "tooling": ESCALATE,
}

# simulation-triage ANALYSIS.root_cause -> rework target.
TRIAGE_ROOT_CAUSE: dict[str, str] = {
    "rtl-design": "rtl-design",
    "simulation-plan": "simulation-plan",
    "specification": "specification",
    "simulation": ESCALATE,
}

_PPA_STAGES = {"synthesis", "power-analysis", "timing-analysis"}


def _decision(
    decision: str, rule: str, *, need: str | None = None, reason_hint: str | None = None
) -> dict:
    """Build the result dict; optional keys (need / reason_hint) omitted when None."""
    out = {"decision": decision, "rule": rule}
    if need is not None:
        out["need"] = need
    if reason_hint is not None:
        out["reason_hint"] = reason_hint
    return out


def route(
    failed_rule: str,
    *,
    failure_kind: str | None = None,
    failures: list[dict] | None = None,
    fail_reason: str | None = None,
    root_cause: str | None = None,
    analysis_state: str | None = None,
    confidence: str | None = None,
) -> dict:
    """Return {decision, rule, [need], [reason_hint]}.

    decision ∈ {<stage>, ESCALATE, NEED_INPUT}. Total over all inputs — any value
    outside a known enum falls through to a named `unrouted*` ESCALATE (never a
    KeyError, never a silent drop). Every routing key is a closed enum.
    """
    # 1. Terminal stage — no DAG-internal target.
    if failed_rule == "frontend-signoff":
        return _decision(ESCALATE, "terminal_frontend_signoff", reason_hint=fail_reason)

    # 2. lint-cdc — input-provenance (U4). Category names which input class
    # failed; route to that input's producer. Unroutable/tooling -> escalate.
    if failed_rule == "lint-cdc":
        if not failures:
            return _decision(ESCALATE, "lint_no_category", reason_hint=fail_reason)
        cat = failures[0].get("category")
        if cat not in LINT_CATEGORY:
            return _decision(
                ESCALATE, "unrouted:unknown_category", reason_hint=fail_reason
            )
        target = LINT_CATEGORY[cat]
        return _decision(
            target, f"lint_category:{cat}->{target}", reason_hint=fail_reason
        )

    # 3. Fixed-target stages.
    if failed_rule in FIXED_TARGET:
        target = FIXED_TARGET[failed_rule]
        return _decision(
            target, f"fixed:{failed_rule}->{target}", reason_hint=fail_reason
        )

    # 4. simulation — routed on triage ANALYSIS (landed analysis.json, supplied as args).
    if failed_rule == "simulation":
        if analysis_state == "skipped":
            return _decision(ESCALATE, "triage_skipped")
        if root_cause is None or analysis_state is None:
            return _decision(NEED_INPUT, "need_input:root_cause", need="root_cause")
        # confidence-gated authority: only a high-confidence verdict auto-routes;
        # medium/low (or missing) surfaces to the operator (spec §3.4).
        if confidence != "high":
            return _decision(ESCALATE, "triage_low_confidence")
        if root_cause not in TRIAGE_ROOT_CAUSE:
            return _decision(ESCALATE, "unrouted:unknown_root_cause")
        target = TRIAGE_ROOT_CAUSE[root_cause]
        return _decision(target, f"triage_root_cause:{root_cause}->{target}")

    # 5. PPA-class stages — failure_kind dispatch.
    if failed_rule in _PPA_STAGES:
        if failure_kind == "infra":
            return _decision(ESCALATE, "failure_kind_infra", reason_hint=fail_reason)
        if failure_kind == "tooling":
            # Gate on the closed-enum failed_rule, NOT on failures[] presence:
            # synthesis/timing schemas allow additionalProperties, so a stray
            # failures[] there would pass validation and mis-route.
            if failed_rule == "power-analysis" and failures:
                cat = failures[0]["category"]
                hint = failures[0].get("error_summary")
                if cat not in PA_CATEGORY:
                    return _decision(
                        ESCALATE, "unrouted:unknown_category", reason_hint=hint
                    )
                target = PA_CATEGORY[cat]
                return _decision(
                    target, f"pa_category:{cat}->{target}", reason_hint=hint
                )
            return _decision(ESCALATE, "tooling_no_route", reason_hint=fail_reason)
        if failure_kind == "ppa":
            return _decision("rtl-design", "ppa->rtl-design", reason_hint=fail_reason)

    # Defensive: unmodeled (failed_rule, failure_kind) — escalate, never silent.
    return _decision(ESCALATE, "unrouted")


def _inputs_from_result_json(path: str) -> dict:
    ss = json.loads(Path(path).read_text()).get("stage_specific", {})
    return {
        "failure_kind": ss.get("failure_kind"),
        "failures": ss.get("failures"),
        "fail_reason": ss.get("fail_reason"),
    }


def main() -> None:
    p = argparse.ArgumentParser(
        prog="route.py", description="VeriPower deterministic rework-router"
    )
    p.add_argument("--failed-rule", required=True)
    p.add_argument(
        "--result-json",
        default=None,
        help="canonical result.json path (PPA / lint-cdc / simulation-plan)",
    )
    p.add_argument(
        "--root-cause",
        default=None,
        help="simulation-triage landed analysis.json root_cause (simulation only)",
    )
    p.add_argument(
        "--analysis-state",
        default=None,
        help="simulation-triage landed analysis.json analysis_state (simulation only)",
    )
    p.add_argument(
        "--confidence",
        default=None,
        help="triage ANALYSIS confidence (simulation only)",
    )
    args = p.parse_args()

    kwargs: dict = {
        "root_cause": args.root_cause,
        "analysis_state": args.analysis_state,
        "confidence": args.confidence,
    }
    if args.result_json:
        kwargs.update(_inputs_from_result_json(args.result_json))

    print(json.dumps(route(args.failed_rule, **kwargs), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
