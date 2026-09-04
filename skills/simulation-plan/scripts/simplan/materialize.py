"""The materialize-scaffold verb — check the plan's agents against the DUT boundary.

What the DUT looks like is NOT injected. Signals, clocks and the reset polarity are read from
top-io.json / clocks.json by simulation itself, at render time. A stored copy could disagree with
the source after either moved, and had no totality — a port absent from it rendered as a DUT port
bound to nothing. What this verb checks is the assignment the plan author made: that every
agent's interface_groups resolve, and hold data ports. The check hints a testpoint covers are
read by simulation by check_id, and the requirements they name by id; nothing is copied here.
"""

import json
import sys
from pathlib import Path

from simplan._plan import SCAFFOLD_NAME


def materialize(scaffold: dict, ports: list) -> dict:
    by_group: dict[str, list[dict]] = {}
    for s in ports:
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
                f"declare interface_groups (names from top-io.json interface_group). "
                f"Valid groups: {valid_groups}."
            )
        unknown = [g for g in groups if g not in by_group]
        if unknown:
            sys.exit(
                f"materialize-scaffold: agent {aname!r} references unknown interface_group(s) "
                f"{unknown}. Valid groups in top-io.json: {valid_groups}."
            )
        if len(groups) != len(set(groups)):
            dupes = sorted({g for g in groups if groups.count(g) > 1})
            sys.exit(
                f"materialize-scaffold: agent {aname!r} has duplicate interface_groups "
                f"entries: {dupes}."
            )
        matched = [s for g in groups for s in by_group[g] if s.get("role") == "data"]
        if not matched:
            sys.exit(
                f"materialize-scaffold: agent {aname!r} has no data ports: its "
                f"interface_groups {groups} hold only clock/reset, which the bench drives. "
                f"Give it the ports it is meant to drive or observe."
            )
        matched_names = [s["name"] for s in matched]
        dupe_names = sorted({n for n in matched_names if matched_names.count(n) > 1})
        if dupe_names:
            sys.exit(
                f"materialize-scaffold: agent {aname!r} has duplicate signal name(s) "
                f"{dupe_names} across its interface_groups {groups} — would emit duplicate "
                f"SV declarations."
            )
    return scaffold


def run(plan_dir, spec_workdir) -> int:
    """Reads tb-scaffold.json raw rather than through _plan.load_plan: this verb runs BEFORE
    check-scaffold, on a file that may not validate yet, and it touches nothing in the other two
    sidecars."""
    scaffold_path = Path(plan_dir) / SCAFFOLD_NAME
    try:
        scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"materialize-scaffold: {scaffold_path} not found.")
    except json.JSONDecodeError as e:
        sys.exit(f"materialize-scaffold: {scaffold_path} is not valid JSON: {e}")
    ports_path = Path(spec_workdir) / "top-io.json"
    try:
        ports = json.loads(ports_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(
            f"materialize-scaffold: {ports_path} not found; check the --spec path."
        )
    except json.JSONDecodeError as e:
        sys.exit(f"materialize-scaffold: {ports_path} is not valid JSON: {e}")
    materialize(scaffold, ports)
    print(
        f"materialize-scaffold: {len(scaffold.get('agents', []))} agent(s) resolve against "
        f"{ports_path}"
    )
    return 0
