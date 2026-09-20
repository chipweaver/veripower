"""Validate the complete plan used by check-scaffold and finalize.

Checks structure, references, boundary ownership and check coverage. Simulation
reads the declared boundary directly when generating its scaffold.
"""

import json
import sys
from pathlib import Path

from simplan._plan import PlanError, load_plan
from simplan.hints import HintsError, load_check_hints


def semantic_errors(scaffold: dict) -> list:
    """Referential-integrity checks the JSON Schema cannot express: name uniqueness,
    observer/inports/sequences.agent/tests.seqs/testpoints.seqs
    resolution,
    and option-c (observer omitted with multiple agents). Returns human-readable errors."""
    agents = scaffold.get("agents", [])
    agent_name_list = [a.get("name") for a in agents]
    agent_names = set(agent_name_list)
    seq_name_list = [s.get("name") for s in scaffold.get("sequences", [])]
    seq_names = set(seq_name_list)
    errs = []

    # Uniqueness — the schema requires name present+string, NOT unique. Duplicate agent /
    # sequence names collide in generated TB filenames + env declarations (SV redeclaration).
    dup_agents = sorted({n for n in agent_name_list if agent_name_list.count(n) > 1})
    if dup_agents:
        errs.append(
            f"agents[].name duplicated: {dup_agents}. Each agent name must be unique."
        )
    dup_seqs = sorted({n for n in seq_name_list if seq_name_list.count(n) > 1})
    if dup_seqs:
        errs.append(
            f"sequences[].name duplicated: {dup_seqs}. Each sequence name must be unique."
        )

    sb = scaffold.get("scoreboard") or {}
    observer = sb.get("observer")
    if observer in (None, ""):
        if len(agents) > 1:
            errs.append(
                f"scoreboard.observer omitted but {len(agents)} agents declared — ambiguous "
                f"observer (the scaffold would silently compare the last agent's stream). Name "
                f"the observer agent explicitly. "
                f"Agents: {sorted(n for n in agent_names if n)}."
            )
    else:
        if observer not in agent_names:
            errs.append(
                f"scoreboard.observer {observer!r} is not in agents[] "
                f"{sorted(n for n in agent_names if n)}. It names the ONE observer agent whose "
                f"monitor stream the scoreboard compares — an agent name, not a txn type, a DUT "
                f"signal list or a free description."
            )

    for ag in (scaffold.get("rm") or {}).get("inports", []):
        if ag not in agent_names:
            errs.append(
                f"rm.inports entry {ag!r} is not in agents[] "
                f"{sorted(n for n in agent_names if n)}. inports name the agents feeding the "
                f"RM — an agent name, not a txn type or an arbitrary signal."
            )

    for s in scaffold.get("sequences", []):
        ag = s.get("agent")
        if ag not in agent_names:
            errs.append(
                f"sequences[{s.get('name')!r}].agent {ag!r} not in agents[] "
                f"{sorted(n for n in agent_names if n)}."
            )

    for t in scaffold.get("tests", []):
        for sn in t.get("seqs", []):
            if sn not in seq_names:
                errs.append(
                    f"tests[{t.get('name')!r}].seqs entry {sn!r} not in sequences[] "
                    f"{sorted(n for n in seq_names if n)}."
                )

    # The testpoint -> sequence edge. It used to be written by the simulation stage's env child
    # into a verify-handoff.json nothing else read; it is the plan author's judgment, so it is
    # declared here and the verify child reads it from the plan like every other plan fact.
    for tp in scaffold.get("testpoints", []):
        for sn in tp.get("seqs", []):
            if sn not in seq_names:
                errs.append(
                    f"testpoints[{tp.get('id')!r}].seqs entry {sn!r} not in sequences[] "
                    f"{sorted(n for n in seq_names if n)}."
                )

    return errs


def coverage_errors(scaffold: dict, check_hints: list) -> list:
    """Each authored check is covered or explicitly skipped; all references resolve.

    Semantic adequacy and justified exclusions remain the plan review's responsibility.
    """
    check_ids = {h["check_id"] for h in check_hints if h.get("check_id")}
    covered, errs = set(), []
    for tp in scaffold.get("testpoints", []):
        for cid in tp.get("covers") or []:
            covered.add(cid)
            if cid not in check_ids:
                errs.append(
                    f"testpoint {tp.get('id')!r} covers references unknown check_id {cid!r} "
                    f"(not in the authored check hints)."
                )
    skipped = {s.get("check_id") for s in scaffold.get("skipped_checks", [])}
    uncovered = sorted(c for c in check_ids if c not in covered and c not in skipped)
    if uncovered:
        errs.append(
            f"uncovered check_hints: {uncovered} (cover each via testpoints[].covers[] or list "
            f"it in skipped_checks[] with a reason)."
        )
    return errs


def verdict(plan_dir, spec_workdir) -> list:
    """Every violation the 3-layer gate finds, as a list of readable errors (empty = clean).
    Short-circuits: a structural failure makes the later layers meaningless, and one
    unresolved name makes the coverage join unreadable. finalize re-runs this in-process, so
    the layers live here rather than inside run()."""
    try:
        plan = load_plan(plan_dir)
    except PlanError as e:
        return [str(e)]
    try:
        check_hints = load_check_hints(spec_workdir)
    except HintsError as e:
        return [str(e)]
    return (
        semantic_errors(plan)
        or boundary_errors(plan, spec_workdir)
        or scenario_errors(plan, spec_workdir)
        or coverage_errors(plan, check_hints)
    )


def scenario_errors(scaffold: dict, spec_workdir) -> list:
    """Every power scenario a requirements.json bound names must be one this plan defines.

    The engineer's power bound may name the scenario it applies to; power-analysis compares
    against that scenario's measurement, seven stages from here. Catching the missing scenario
    here, where the scenarios are authored, is the difference between a plan round and a whole
    pipeline round."""
    try:
        rows = json.loads(
            (Path(spec_workdir) / "requirements.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as e:
        return [f"requirements.json unreadable: {e}"]
    defined = {ps.get("id") for ps in scaffold.get("power_scenarios", [])}
    return [
        f"requirements.json {r['id']} bounds power in scenario {r['target']['scenario']!r}, "
        f"which power-scenarios.json does not define (defined: {sorted(d for d in defined if d)})."
        for r in rows
        if r.get("judge") == "power-analysis"
        and "scenario" in (r.get("target") or {})
        and r["target"]["scenario"] not in defined
    ]


def boundary_errors(scaffold: dict, spec_workdir) -> list:
    """Resolve each agent's groups and assign every data port exactly once."""
    try:
        ports = json.loads(
            (Path(spec_workdir) / "top-io.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as e:
        return [f"top-io.json unreadable: {e}"]
    by_group: dict[str, list[dict]] = {}
    for port in ports:
        by_group.setdefault(port["interface_group"], []).append(port)
    owner: dict[str, str] = {}
    errs = []
    for agent in scaffold["agents"]:
        groups = agent["interface_groups"]
        unknown = sorted(set(groups) - by_group.keys())
        if unknown:
            errs.append(
                f"agent {agent['name']!r} references unknown interface_group(s) {unknown}"
            )
        matched = [
            p for g in groups for p in by_group.get(g, []) if p["role"] == "data"
        ]
        if not matched:
            errs.append(
                f"agent {agent['name']!r} has no data ports in interface_groups {groups}"
            )
        names = [p["name"] for p in matched]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            errs.append(
                f"agent {agent['name']!r} has duplicate signal name(s) {duplicates}"
            )
        for group in groups:
            if group in owner:
                errs.append(
                    f"interface_group {group!r} is claimed by both {owner[group]!r} "
                    f"and {agent['name']!r}; each group must be assigned once"
                )
            owner[group] = agent["name"]
    unclaimed = sorted(
        {
            p["interface_group"]
            for p in ports
            if p.get("role") == "data" and p.get("interface_group") not in owner
        }
    )
    if unclaimed:
        errs.append(
            f"interface_group(s) {unclaimed} hold data ports no agent claims, so nothing "
            f"would drive them and the DUT instantiation would leave those ports open. Give "
            f"some agent each group, or move the ports to a group that has one."
        )
    return errs


def run(plan_dir, spec_workdir) -> int:
    """check-scaffold: 3-layer gate (structural -> semantic -> coverage, short-circuit).
    exit 0 with 'check-scaffold: OK ...' / exit 1 with a fix-oriented message to stderr."""
    errors = verdict(plan_dir, spec_workdir)
    if errors:
        sys.exit(
            "check-scaffold: the plan sidecars are invalid:\n  - "
            + "\n  - ".join(errors)
            + "\nFix them (each sidecar's field contract is its own"
            " references/*.schema.json) and re-run."
        )
    print("check-scaffold: OK")
    return 0
