#!/usr/bin/env python3
"""Read the specification boundary at render time and bind every declared port."""

from __future__ import annotations

import json
import sys
from pathlib import Path


class Boundary:
    """Declared top-level controls and data; clock domains describe hardware timing."""

    def __init__(self, spec_dir):
        documents = {}
        for filename in ("top-io.json", "clocks.json"):
            path = Path(spec_dir) / filename
            try:
                documents[filename] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                sys.exit(f"[sim bootstrap] cannot read {path}: {error}")
        ports = documents["top-io.json"]
        clocks = documents["clocks.json"]
        by_name = {c["name"]: c for c in clocks}
        self.clocks: list[dict] = []
        self.resets: list[dict] = []
        self.groups: dict[str, list[dict]] = {}
        self.group_domain: dict[str, set[str]] = {}
        self.port_order: list[str] = []
        for p in ports:
            self.port_order.append(p["name"])
            if p["clock_domain"] not in by_name:
                sys.exit(
                    f"[sim bootstrap] port {p['name']!r} references clock_domain "
                    f"{p['clock_domain']!r} absent from clocks.json"
                )
            if p["role"] == "clock":
                if p["name"] not in by_name:
                    sys.exit(
                        f"[sim bootstrap] clock port {p['name']!r} is absent from clocks.json"
                    )
                self.clocks.append({**p, "period_ns": by_name[p["name"]]["period_ns"]})
            elif p["role"] == "reset":
                if p.get("reset_polarity") not in (0, 1):
                    sys.exit(
                        f"[sim bootstrap] reset port {p['name']!r} needs reset_polarity 0 or 1"
                    )
                self.resets.append(p)
            else:
                group = p["interface_group"]
                self.groups.setdefault(group, []).append(p)
                self.group_domain.setdefault(group, set()).add(p["clock_domain"])

    def clock_for(self, groups: list[str]) -> str | None:
        """A single top-level clock can seed an interface connection.

        Other observation arrangements are authored in the interface instantiation.
        No clock is invented or selected from several hardware domains.
        """
        domains = {d for g in groups for d in self.group_domain.get(g, set())}
        if len(domains) == 1:
            domain = next(iter(domains))
            if any(c["name"] == domain for c in self.clocks):
                return domain
        return None


def dut_port_map(agents: list[dict], boundary) -> str:
    """Validate the agent-to-group assignment and build tb_top's DUT port bindings.

    Walks the BOUNDARY, not the agents, so a port cannot be silently left out: every entry in
    top-io.json is top-level control or resolves to exactly one agent, and anything else exits here.
    Called during the in-memory render pass before any file is written, so a failure leaves
    nothing on disk. Returns the block with a leading ',\\n' so it concatenates after the
    top-level control ports.
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
    control_ports = {port["name"] for port in boundary.clocks + boundary.resets}
    lines: list[str] = []
    for name in boundary.port_order:
        if name in control_ports:
            continue  # connected by the caller
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
