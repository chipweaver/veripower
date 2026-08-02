#!/usr/bin/env python3
"""The DUT boundary, read from specification's own declaration at render time.

The scaffold used to carry a restatement of this — per-agent `interface.signals`,
`transaction.fields`, `primary_clock`, `additional_clocks`, `reset` — injected once by
simulation-plan's materialize step. A stored restatement has two properties this does not:
it can disagree with the source after either moves, and it has no totality, so a port
simply absent from it produced a DUT instantiation missing that port. Verilog binds an
omitted port to nothing and VCS compiles it without an error, so the domain or the signal
was dead for the whole run with no report naming the bench.

Deriving it here removes both. The DUT instantiation is built by walking the ports, so
omitting one is not expressible, and every value is whatever the sidecar says now.
"""

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
    """Clocks, reset and the per-group data ports, as specification declared them.

    `primary` is the clock the agents' virtual interfaces run on; `extra` are the rest,
    each of which the bench generates and binds. `reset.polarity` is what lets the bench
    keep one active-low reset for every DUT and invert once, at the port.
    """

    def __init__(self, spec_dir):
        ports = _read(spec_dir, "top-io.json")
        clocks = _read(spec_dir, "clocks.json")
        by_name = {c["name"]: c for c in clocks}

        primary_row = next(
            (c for c in clocks if c.get("relationship") == "primary"), None
        )
        if primary_row is None:
            sys.exit(
                "[sim bootstrap] no clocks.json entry with relationship=='primary' — "
                "refusing to pick one as the TB main clock. Re-run specification."
            )

        self.primary = None
        self.extra: list[dict] = []
        self.reset = None
        self.groups: dict[str, list[dict]] = {}
        self.group_domain: dict[str, set[str]] = {}
        self.port_order: list[str] = []

        for p in ports:
            self.port_order.append(p["name"])
            role = p.get("role")
            if role == "clock":
                entry = by_name.get(p["name"])
                if entry is None:
                    sys.exit(
                        f"[sim bootstrap] top-io.json declares clock port {p['name']!r} with "
                        f"no clocks.json entry, so the bench cannot generate it. Add it to "
                        f"clocks.json (re-run specification), or correct the port's role."
                    )
                rec = {"name": p["name"], "period_ns": entry["period_ns"]}
                if p["name"] == primary_row["name"]:
                    self.primary = rec
                else:
                    self.extra.append(rec)
            elif role == "reset":
                if p.get("reset_polarity") not in (0, 1):
                    sys.exit(
                        f"[sim bootstrap] top-io.json reset port {p['name']!r} has "
                        f"reset_polarity={p.get('reset_polarity')!r}, not 0 or 1. The bench "
                        f"drives reset and cannot guess which level asserts it."
                    )
                self.reset = {"name": p["name"], "polarity": p["reset_polarity"]}
            else:
                g = p["interface_group"]
                self.groups.setdefault(g, []).append(
                    {"name": p["name"], "width": p["width"]}
                )
                self.group_domain.setdefault(g, set()).add(p["clock_domain"])

        if self.primary is None:
            sys.exit(
                f"[sim bootstrap] clocks.json names {primary_row['name']!r} primary, but "
                f"top-io.json declares no port with that name and role=='clock'."
            )
        if self.reset is None:
            sys.exit(
                "[sim bootstrap] top-io.json declares no port with role=='reset'. The bench "
                "drives one; re-run specification."
            )

    @property
    def bench_driven(self) -> set[str]:
        """Ports the bench owns: no agent declares them and none appears in a vif."""
        return {
            self.primary["name"],
            self.reset["name"],
            *(c["name"] for c in self.extra),
        }

    def signals_for(self, groups: list[str]) -> list[dict]:
        return [s for g in groups for s in self.groups.get(g, [])]

    def clock_for(self, agent_name: str, groups: list[str]) -> str:
        """The TB net carrying the clock this agent's ports are declared in.

        top-io.json states a `clock_domain` per port and the bench used to drop it, wiring
        every virtual interface to the primary clock. On a single-clock DUT that is the same
        thing; on a multi-clock one the agent then samples a second-domain port on a clock it
        does not belong to, which is not a race the DUT has — it is one the bench invented.

        `clk` is the primary's TB net; the others are declared under their own port name.
        """
        domains = {d for g in groups for d in self.group_domain.get(g, set())}
        if len(domains) > 1:
            sys.exit(
                f"[sim bootstrap] agent {agent_name!r} spans clock domains {sorted(domains)}: "
                f"one virtual interface has one clock, so its ports cannot be sampled "
                f"coherently. Split it into one agent per domain in tb-scaffold.json."
            )
        domain = domains.pop() if domains else self.primary["name"]
        if domain == self.primary["name"]:
            return "clk"
        if any(c["name"] == domain for c in self.extra):
            return domain
        sys.exit(
            f"[sim bootstrap] agent {agent_name!r} is in clock_domain {domain!r}, which "
            f"top-io.json declares no clock port for. The bench cannot generate it; correct "
            f"the ports' clock_domain or add the clock (re-run specification)."
        )
