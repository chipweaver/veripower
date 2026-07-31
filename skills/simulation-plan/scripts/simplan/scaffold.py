"""The check-scaffold gate — validate the three plan sidecars.

Runs AFTER the materialize-scaffold verb, so agents[] carry the injected
interface/transaction objects, which the schema tolerates but does not deep-validate.

The three layers short-circuit because each makes the next readable: a schema violation
makes the referential checks meaningless, and one unresolved name makes the coverage join
unreadable. The merge in `_plan.load_plan` exists for the middle layer — the referential
integrity spans all three files (`power_scenarios[].sequence_ref` and `tests[].seqs[]` both
resolve against `sequences[]`), so no single schema can express it.

finalize re-runs the whole thing in-process. That is affordable because every layer is a
set operation over the workdir's own files plus the authored check hints, and it is what
makes the verdict part of the proof rather than a dev-time lint: a clean gate stays true
unless an artifact was edited afterwards.

Pairs with simulation's renderer and its thin consumer-side backstops (defense-in-depth for
scaffolds that bypass this gate).
"""

import sys

from simplan._plan import PlanError, load_plan
from simplan.hints import HintsError, load_check_hints


def semantic_errors(scaffold: dict) -> list:
    """Referential-integrity checks the JSON Schema cannot express: name uniqueness,
    observer/inports/sequences.agent/tests.seqs/power_scenarios.sequence_ref resolution,
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

    for ps in scaffold.get("power_scenarios", []):
        ref = ps.get("sequence_ref")
        if ref not in seq_names:
            errs.append(
                f"power_scenarios[{ps.get('id')!r}].sequence_ref {ref!r} not in sequences[] "
                f"{sorted(n for n in seq_names if n)}."
            )

    return errs


def coverage_errors(scaffold: dict, check_hints: list) -> list:
    """Bidirectional coverage matrix: every authored check_id is covered (in some
    testpoints[].covers[]) or skipped (in skipped_checks[]); every non-empty covers[] entry
    resolves to a real check_id. The inline existence/non-emptiness is guaranteed by
    construction (the materialize-scaffold verb), so it is not re-checked here.

    The dangling-covers half reads as redundant with materialize's own guard and is not.
    That guard is a build-time precondition; this is the gate, and the documented fix loop
    re-runs the gate alone. The uncovered-check_hints message below steers the author into
    hand-adding a check_id to covers[], an edit made after materialize already wrote the
    file, so a typo in that id is caught here or nowhere. The hints are re-read on every run,
    leaving a scaffold materialized against an earlier set free
    to dangle against the current. references/plan-review-task-contract.md then puts this
    defect class out of scope for the LLM reviewer on the strength of this check, so
    dropping it would leave the class owned by nobody."""
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
    return semantic_errors(plan) or coverage_errors(plan, check_hints)


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
