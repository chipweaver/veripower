"""VeriPower deterministic rework-router.

Pure evaluator: maps a SELF-DESCRIBING stage failure to a rework target, or to
ESCALATE. Holds no state and does no I/O. Most failures route on the closed-enum
`failed_rule` / `failure_kind`; lint-cdc instead routes by input-provenance —
`failures[0].category` names which upstream input produced the failure (the SGDC
seed vs. the RTL), so a CDC failure can route to `specification` instead of always
blaming `rtl-design` (U4). Composed unchanged inside schedule.py; the sole home
for the static failure->target maps — no other file (SKILL.md / ARCHITECTURE.md /
schemas) may restate them.

Ambiguous simulation failures are NOT routed here: schedule.py dispatches
`simulation-triage`, whose reap (kernel._derive_triage) mints a diagnosis via the
`TRIAGE_ROOT_CAUSE` map below, and the confidence/reliability gate lives in
schedule._reliable (§3.4). route() is only ever called for non-simulation,
self-describing failures.
"""

from __future__ import annotations

ESCALATE = "ESCALATE"

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

# simulation-triage ANALYSIS.root_cause -> rework target. Consumed by
# kernel._derive_triage at triage-reap time (NOT by route() — simulation is not
# self-describing and never reaches route()); kept here as the single map home.
TRIAGE_ROOT_CAUSE: dict[str, str] = {
    "rtl-design": "rtl-design",
    "simulation-plan": "simulation-plan",
    "specification": "specification",
    "simulation": ESCALATE,
}

_PPA_STAGES = {"synthesis", "power-analysis", "timing-analysis"}


def _decision(decision: str, rule: str, *, reason_hint: str | None = None) -> dict:
    """Build the result dict; optional reason_hint omitted when None."""
    out = {"decision": decision, "rule": rule}
    if reason_hint is not None:
        out["reason_hint"] = reason_hint
    return out


def route(
    failed_rule: str,
    *,
    failure_kind: str | None = None,
    failures: list[dict] | None = None,
    fail_reason: str | None = None,
) -> dict:
    """Return {decision, rule, [reason_hint]} for a self-describing failure.

    decision ∈ {<stage>, ESCALATE}. Total over all inputs — any value outside a
    known enum falls through to a named `unrouted*` ESCALATE (never a KeyError,
    never a silent drop). Every routing key is a closed enum. `failed_rule ==
    "simulation"` never reaches route() (schedule dispatches triage first).
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

    # 4. PPA-class stages — failure_kind dispatch.
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
