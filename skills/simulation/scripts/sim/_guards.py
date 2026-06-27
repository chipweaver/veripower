#!/usr/bin/env python3
"""sim scaffold contract guards: the gate-bypass consumer defense.

Reads the canonical agent I/O shape that simulation-plan's materialize step produces
(agent["interface"]["signals"] / agent["transaction"]["fields"]) and fails loud — rather
than emitting a degenerate/garbage TB — on an empty interface (root cause A), a non-string
compare_txn, a non-list inports/seqs, or a signal colliding with / duplicated across the
clk/reset ports. Primary enforcement is the simulation-plan scaffold gate; these guard the
primitives for any direct/gate-bypass caller. Per-stage copy (campaign §3 — no shared lib).
"""

from __future__ import annotations

import sys


def _agent_io(agent: dict) -> tuple[list[dict], list[dict]]:
    """Read the canonical agent I/O shape materialized by simulation-plan's materialize step:
    agent["interface"]["signals"] = [{name, width}] and agent["transaction"]["fields"] =
    [{name, width, type?, rand?}]. Fail loud if interface.signals is missing/empty: a degenerate
    empty interface is root cause A (TB compiles but is functionally empty, sim crashes downstream).
    """
    aname = agent.get("name", "<unnamed>")
    signals = agent.get("interface", {}).get("signals")
    if not signals:
        sys.exit(
            f"scaffold: agent {aname!r} has no interface.signals. Rerun simulation-plan's "
            f"materialize step: agents declare interface_groups and the materializer fills "
            f"signals from plan-data.json.interfaces[] "
            f"(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )
    fields = agent.get("transaction", {}).get("fields", [])
    return signals, fields


def _check_str_or_omitted(value, field: str, module: str) -> None:
    """Backstop: scoreboard.compare_txn must be a single '<module>_<agent>_txn' string (or omitted).
    A list/dict reaching the bare .replace() crashes with an opaque AttributeError; fail loud instead."""
    if value not in (None, "") and not isinstance(value, str):
        sys.exit(
            f"scaffold: {field} must be a single '{module}_<agent>_txn' string (or omitted), "
            f"got {type(value).__name__} {value!r}. Re-run simulation-plan (scaffold gate). "
            f"See skills/simulation-plan/SKILL.md scaffold-spec contract."
        )


def _check_list_or_omitted(value, field: str) -> None:
    """Backstop: rm.inports / tests[].seqs must be a list (or omitted). A bare string silently
    iterates character-by-character into garbage SV; fail loud instead."""
    if value not in (None, "") and not isinstance(value, list):
        sys.exit(
            f"scaffold: {field} must be a list (or omitted), got {type(value).__name__} "
            f"{value!r}. A bare string silently iterates character-by-character. Re-run "
            f"simulation-plan (scaffold gate)."
        )


def validate_ports(agents: list[dict], clk_port_name: str, rst_port_name: str) -> str:
    """Validate per-agent signal names and build the DUT port-map block.

    Fail loud (sys.exit) on a signal colliding with the clock/reset port name or duplicated
    across agents. Called during the in-memory render pass *before any file is written*, so a
    collision leaves nothing on disk (U1 atomicity). Returns the dut_port_map string for tb_top
    (leading ',\\n' so it concatenates after .rst(rst_n))."""
    dut_port_lines: list[str] = []
    seen_signals: set[str] = {clk_port_name, rst_port_name}
    first_owner: dict[str, str] = {}
    for agent in agents:
        aname = agent["name"]
        signals, _ = _agent_io(agent)
        for s in signals:
            sig = s["name"]
            if sig in {clk_port_name, rst_port_name}:
                sys.exit(
                    f"scaffold: agent '{aname}' signal '{sig}' collides with "
                    f"clock/reset port name (clk={clk_port_name!r}, rst={rst_port_name!r}). "
                    f"Rename the signal in scaffold-spec or fix primary_clock.dut_port_name / "
                    f"reset.dut_port_name to disambiguate."
                )
            if sig in seen_signals:
                sys.exit(
                    f"scaffold: signal '{sig}' duplicated across agents "
                    f"(first declared in '{first_owner[sig]}', conflict in '{aname}'). "
                    f"Adjust the agents' interface_groups in scaffold-specification.json so "
                    f"the groups do not overlap, then re-run simulation-plan's materialize step "
                    f"(an agent's signals must be unique within the scaffold)."
                )
            seen_signals.add(sig)
            first_owner[sig] = aname
            dut_port_lines.append(f"    .{sig}({aname}_if.{sig}),")
    if dut_port_lines:
        dut_port_lines[-1] = dut_port_lines[-1].rstrip(",")
        return ",\n" + "\n".join(dut_port_lines)
    return ""
