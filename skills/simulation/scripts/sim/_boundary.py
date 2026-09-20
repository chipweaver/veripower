#!/usr/bin/env python3
"""Read the specification boundary at render time and bind every declared port."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _read(spec_dir: Path, name: str):
    f = Path(spec_dir) / name
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except OSError:
        sys.exit(
            f"[sim bootstrap] {f} not found. It is a declared input of this stage, injected "
            f"into dispatch.json as `spec`; specification writes it."
        )
    except json.JSONDecodeError as e:
        sys.exit(f"[sim bootstrap] {f} is not valid JSON: {e}")


class Boundary:
    """Declared top-level controls and data; clock domains describe hardware timing."""

    def __init__(self, spec_dir):
        ports = _read(spec_dir, "top-io.json")
        clocks = _read(spec_dir, "clocks.json")
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

    @property
    def control_ports(self) -> set[str]:
        """Controls connected at TB top, outside the agents' data fields."""
        return {p["name"] for p in self.clocks + self.resets}

    def signals_for(self, groups: list[str]) -> list[dict]:
        return [s for g in groups for s in self.groups.get(g, [])]

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
