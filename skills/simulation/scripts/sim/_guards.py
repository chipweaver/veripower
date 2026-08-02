#!/usr/bin/env python3
"""sim scaffold contract guards: the gate-bypass consumer defense.

Reads the canonical agent I/O shape simulation-plan's materialize step produces
(agent["interface"]["signals"] / agent["transaction"]["fields"]) and exits rather than emitting
a TB that would compile and verify nothing: an empty interface, or a signal that collides with
the clock or reset port or repeats across agents.

These two and no others. tb-scaffold.schema.json types every field simulation-plan authors and
is validated where the file is written, so re-checking a type here would be a second copy of
that. What it does not cover is stated in its own description: it tolerates the interface and
transaction objects materialize-scaffold injects, and names this module as their owner.
"""

from __future__ import annotations

import sys


def _agent_io(agent: dict) -> tuple[list[dict], list[dict]]:
    """Read the canonical agent I/O shape materialized by simulation-plan's materialize step:
    agent["interface"]["signals"] = [{name, width}] and agent["transaction"]["fields"] =
    [{name, width, type?, rand?}]. Exit if interface.signals is missing or empty: the TB it
    would render compiles and drives nothing.
    """
    aname = agent.get("name", "<unnamed>")
    signals = agent.get("interface", {}).get("signals")
    if not signals:
        sys.exit(
            f"[sim bootstrap] agent {aname!r} has no interface.signals. Rerun simulation-plan's "
            f"materialize step: agents declare interface_groups and the materializer fills "
            f"signals from top-io.json "
            f"(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )
    fields = agent.get("transaction", {}).get("fields", [])
    return signals, fields


def validate_ports(
    agents: list[dict],
    clk_port_name: str,
    rst_port_name: str,
    extra_clock_names: list[str] | None = None,
) -> str:
    """Validate per-agent signal names and build the DUT port-map block.

    Exit on a signal that collides with a clock or reset port name, or repeats across
    agents. Called during the in-memory render pass before any file is written, so a collision
    leaves nothing on disk. Returns the dut_port_map string for tb_top
    (leading ',\\n' so it concatenates after the bench-owned ports).

    materialize-scaffold already excludes clock and reset ports from interface.signals, so
    the collision branch fires only on a hand-edited scaffold — the gate-bypass case this
    module exists for."""
    bench_owned = {clk_port_name, rst_port_name, *(extra_clock_names or [])}
    dut_port_lines: list[str] = []
    seen_signals: set[str] = set(bench_owned)
    first_owner: dict[str, str] = {}
    for agent in agents:
        aname = agent["name"]
        signals, _ = _agent_io(agent)
        for s in signals:
            sig = s["name"]
            if sig in bench_owned:
                sys.exit(
                    f"[sim bootstrap] agent '{aname}' signal '{sig}' collides with a "
                    f"bench-driven clock/reset port ({sorted(bench_owned)}). The materialize "
                    f"step drops those from interface.signals, so this scaffold was edited by "
                    f"hand; re-run simulation-plan's materialize step."
                )
            if sig in seen_signals:
                sys.exit(
                    f"[sim bootstrap] signal '{sig}' duplicated across agents "
                    f"(first declared in '{first_owner[sig]}', conflict in '{aname}'). "
                    f"Adjust the agents' interface_groups in tb-scaffold.json so "
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
