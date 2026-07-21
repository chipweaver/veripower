"""The materialize-scaffold verb — fill scaffold-specification.json from plan-data.json.

Each agent in scaffold-specification.json is authored by the simulation-plan LLM as
{name, mode, interface_groups:[...]} — group NAMES only (from design.md §1.4.1 Interface
Group). This verb fills each agent's interface.signals + transaction.fields
deterministically from plan-data.json.interfaces[] (grouped by interface_group), so the
LLM never hand-transcribes signal names/widths. Clock/reset signals (identified by the
gated §1.4.1 Role) are kept in interface.signals but excluded from transaction.fields —
they must never be rand txn fields. It also derives primary_clock (from the §1.6
relationship=="primary" clock) and reset (from the §1.4.1 role=="reset" interface) and
writes them into the scaffold, and materializes each testpoints[].inlined_check_hints[]
from the testpoint's covers[] + plan-data check_hints[] (implementation_detail =
verbatim-if-present-else-summary). Fails loud (SystemExit) when an agent omits
interface_groups, names an unknown group, has a duplicate group, a width is non-numeric,
an interface row has an empty Role, there is no primary-relationship clock, there is no
reset-role interface, or a testpoint's covers[] names a check_id absent from plan-data.

Pairs with: simulation's render-scaffold verb consumes the materialized interface.signals /
transaction.fields via its _agent_io() helper.
"""

import json
import sys
from pathlib import Path


def _parse_width(raw, signal_name: str) -> int:
    try:
        return int(str(raw if raw not in (None, "") else "1").strip())
    except ValueError:
        sys.exit(
            f"materialize-scaffold: signal {signal_name!r} has non-numeric width {raw!r} "
            f"(design.md §1.4.1 Width must be an integer)."
        )


def _clk_rst_signal_names(plan_data: dict) -> set:
    """Return the names of clock/reset ports (authoritative §1.4.1 Role). Fails loud on any
    interface row with an empty Role — Role is gated, so an empty value is a spec-gate escape."""
    names = set()
    for s in plan_data.get("interfaces", []):
        role = (s.get("role") or "").strip().lower()
        if not role:
            sys.exit(
                f"materialize-scaffold: interface signal {s.get('signal_name')!r} has empty Role "
                f"(design.md §1.4.1 Role is gated: clock/reset/data). Re-run specification."
            )
        if role in {"clock", "reset"}:
            names.add(s["signal_name"])
        elif not (s.get("direction") or "").strip():
            # A data port with no Direction can't be classed driver vs monitor, so the
            # generated TB is wrong. Direction is gated for data roles — an empty value
            # is a spec-gate escape; fail loud rather than silently pick a default.
            sys.exit(
                f"materialize-scaffold: data signal {s.get('signal_name')!r} has empty Direction "
                f"(design.md §1.4.1 Direction gated: driver/monitor). Re-run specification."
            )
    return names


def _derive_primary_clock(plan_data: dict) -> dict:
    clocks = plan_data.get("clocks", [])
    if not clocks:
        sys.exit(
            "materialize-scaffold: plan-data.json has no clocks[] — primary_clock cannot be "
            "derived (design.md §1.6 Clocks and Frequencies required)."
        )
    primary = next(
        (
            c
            for c in clocks
            if (c.get("relationship") or "").strip().lower() == "primary"
        ),
        None,
    )
    if primary is None:
        sys.exit(
            "materialize-scaffold: no clock with Relationship=='primary' in design.md §1.6 — "
            "a gated §1.6 declares one; refusing to silently pick row-0 as the TB main clock."
        )
    name = (primary.get("clock_name") or "").strip()
    period = (primary.get("period_ns") or "").strip()
    if not name or not period:
        sys.exit(
            f"materialize-scaffold: primary clock row missing clock_name/period_ns "
            f"(name={name!r}, period={period!r}); design.md §1.6 Clock Name + SDC Period required."
        )
    return {"dut_port_name": name, "period_ns": period}


def _derive_reset(plan_data: dict) -> dict:
    for s in plan_data.get("interfaces", []):
        if (s.get("role") or "").strip().lower() == "reset":
            return {"dut_port_name": s["signal_name"]}
    sys.exit(
        "materialize-scaffold: no interface with Role=='reset' in design.md §1.4.1 — "
        "reset.dut_port_name cannot be derived (Role is gated; re-run specification)."
    )


def _materialize_inline(plan_data: dict, scaffold: dict) -> None:
    """Fill testpoints[].inlined_check_hints[] deterministically from covers[] + plan-data.
    implementation_detail = prefer(verbatim, summary). Fails loud on a covers[] check_id absent
    from plan-data (also the gate's reverse check). LLM authors covers[] (clustering) only."""
    by_id = {
        h["check_id"]: h for h in plan_data.get("check_hints", []) if h.get("check_id")
    }
    for tp in scaffold.get("testpoints", []):
        inlined = []
        for cid in tp.get("covers") or []:
            h = by_id.get(cid)
            if h is None:
                sys.exit(
                    f"materialize-scaffold: testpoint {tp.get('id')!r} covers unknown check_id "
                    f"{cid!r} (not in plan-data.json.check_hints[]). Known: {sorted(by_id)}."
                )
            detail = (h.get("implementation_detail_verbatim") or "").strip() or (
                h.get("implementation_detail") or ""
            ).strip()
            entry = {"check_id": cid, "implementation_detail": detail}
            for opt in ("observable", "reference_rule", "latency", "reset_behavior"):
                v = (h.get(opt) or "").strip()
                if v:
                    entry[opt] = v
            inlined.append(entry)
        tp["inlined_check_hints"] = inlined


def materialize(plan_data: dict, scaffold: dict) -> dict:
    interfaces = plan_data.get("interfaces", [])
    exclude = _clk_rst_signal_names(plan_data)
    by_group: dict[str, list[dict]] = {}
    for s in interfaces:
        g = (s.get("interface_group") or "").strip()
        if g:
            by_group.setdefault(g, []).append(s)
    valid_groups = sorted(by_group)

    for agent in scaffold.get("agents", []):
        aname = agent.get("name", "<unnamed>")
        groups = agent.get("interface_groups")
        if not groups:
            sys.exit(
                f"materialize-scaffold: agent {aname!r} has no interface_groups. Each agent must "
                f"declare interface_groups (names from design.md §1.4.1 Interface Group / "
                f"plan-data.json.interfaces[].interface_group). Valid groups: {valid_groups}."
            )
        unknown = [g for g in groups if g not in by_group]
        if unknown:
            sys.exit(
                f"materialize-scaffold: agent {aname!r} references unknown interface_group(s) "
                f"{unknown}. Valid groups in plan-data.json: {valid_groups}."
            )
        if len(groups) != len(set(groups)):
            dupes = sorted({g for g in groups if groups.count(g) > 1})
            sys.exit(
                f"materialize-scaffold: agent {aname!r} has duplicate interface_groups "
                f"entries: {dupes}."
            )
        matched = [s for g in groups for s in by_group[g]]
        matched_names = [s["signal_name"] for s in matched]
        dupe_names = sorted({n for n in matched_names if matched_names.count(n) > 1})
        if dupe_names:
            sys.exit(
                f"materialize-scaffold: agent {aname!r} has duplicate signal name(s) "
                f"{dupe_names} across its interface_groups {groups} — would emit duplicate "
                f"SV declarations."
            )
        signals = [
            {
                "name": s["signal_name"],
                "width": _parse_width(s.get("width"), s["signal_name"]),
            }
            for s in matched
        ]
        agent["interface"] = {"signals": signals}
        agent["transaction"] = {
            "fields": [
                {
                    "name": sig["name"],
                    "width": sig["width"],
                    "type": "logic",
                    "rand": True,
                }
                for sig in signals
                if sig["name"] not in exclude
            ]
        }

    scaffold["primary_clock"] = _derive_primary_clock(plan_data)
    scaffold["reset"] = _derive_reset(plan_data)
    _materialize_inline(plan_data, scaffold)
    return scaffold


def run(plan_data_path, scaffold_path) -> int:
    scaffold_path = Path(scaffold_path)
    try:
        plan_data = json.loads(Path(plan_data_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"materialize-scaffold: {plan_data_path} is not valid JSON: {e}")
    try:
        scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"materialize-scaffold: {scaffold_path} is not valid JSON: {e}")
    scaffold = materialize(plan_data, scaffold)
    scaffold_path.write_text(
        json.dumps(scaffold, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"materialize-scaffold: materialized {len(scaffold.get('agents', []))} agent(s) "
        f"from {plan_data_path}"
    )
    return 0
