#!/usr/bin/env python3
"""sim scaffold contract guards: the agent-to-boundary assignment.

The scaffold no longer carries a copy of the DUT's signals — those come from top-io.json at
render time (`_boundary`). What is left to check is the assignment the plan author made: each
agent names interface_groups, and those groups have to partition the data ports. The three
ways that can fail are an agent with nothing to drive, two agents claiming one group, and a
port no agent claimed — the last of which used to render as a DUT port bound to nothing, which
Verilog accepts and VCS compiles without an error.

These three and no others. tb-scaffold.schema.json types every field simulation-plan authors
and is validated where the file is written, so re-checking a type here would be a second copy.
"""

from __future__ import annotations

import sys


def dut_port_map(agents: list[dict], boundary) -> str:
    """Validate the agent-to-group assignment and build tb_top's DUT port bindings.

    Walks the BOUNDARY, not the agents, so a port cannot be silently left out: every entry in
    top-io.json is bench-driven or resolves to exactly one agent, and anything else exits here.
    Called during the in-memory render pass before any file is written, so a failure leaves
    nothing on disk. Returns the block with a leading ',\\n' so it concatenates after the
    bench-driven ports.
    """
    owner: dict[str, str] = {}
    for agent in agents:
        aname = agent["name"]
        groups = agent.get("interface_groups") or []
        if not any(boundary.groups.get(g) for g in groups):
            sys.exit(
                f"[sim bootstrap] agent {aname!r} has no data ports: its interface_groups "
                f"{groups} are empty or unknown in top-io.json (groups with data ports: "
                f"{sorted(boundary.groups)}). It would drive and observe nothing."
            )
        for g in groups:
            if g in owner:
                sys.exit(
                    f"[sim bootstrap] interface_group {g!r} is claimed by both "
                    f"{owner[g]!r} and {aname!r}. One group is one virtual interface, so its "
                    f"ports would be bound twice; adjust interface_groups in tb-scaffold.json."
                )
            owner[g] = aname

    port_agent = {
        s["name"]: owner[g]
        for g, sigs in boundary.groups.items()
        if g in owner
        for s in sigs
    }
    lines: list[str] = []
    for name in boundary.port_order:
        if name in boundary.bench_driven:
            continue  # emitted by the caller, which knows how it drives each one
        aname = port_agent.get(name)
        if aname is None:
            group = next(
                g
                for g, sigs in boundary.groups.items()
                if any(s["name"] == name for s in sigs)
            )
            sys.exit(
                f"[sim bootstrap] DUT port {name!r} is in interface_group {group!r}, which no "
                f"agent claims, so nothing would drive it and the instantiation would leave it "
                f"open. Give some agent that group in tb-scaffold.json, or move the port to a "
                f"group that has one."
            )
        lines.append(f"    .{name}({aname}_if.{name})")
    return (",\n" + ",\n".join(lines)) if lines else ""
