"""The check-scaffold gate — validate scaffold-specification.json (sim-plan Completion Gate).

Runs AFTER the materialize-scaffold verb (so agents[] carry materialize-injected
interface/transaction, which the schema tolerates but does not deep-validate).
Three layers (each runs only if the prior passed):
  1. Structural — jsonschema Draft 2020-12 against scaffold-specification.schema.json
     (types, enums, required, additionalProperties on authored objects).
  2. Semantic — referential integrity the schema cannot express: compare_txn /
     rm.inports resolve (after stripping the canonical txn wrapper) to a declared
     agent; sequences[].agent / tests[].seqs[] / power_scenarios[].sequence_ref
     resolve to declared agents/sequences; option-c (compare_txn omitted +
     multiple agents -> fail).
  3. Coverage — bidirectional matrix over the LLM judgment vs plan-data.json
     (required --plan-data): every plan-data check_hints[].check_id is covered by
     some testpoints[].covers[] or listed in skipped_checks[]; every non-empty
     covers[] entry resolves to a real check_id. Applied by run() after layers 1-2.

Exits 0 with "check-scaffold: OK ..." on a clean scaffold; otherwise exits non-zero with a
readable, fix-oriented message to stderr. Pairs with simulation render-scaffold's thin
consumer-side backstops (defense-in-depth for scaffolds that bypass this gate).
"""

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

_DEFAULT_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent
    / "references"
    / "scaffold-specification.schema.json"
)


def _format_validation_errors(errors) -> str:
    """Format up to 3 jsonschema errors as 'schema violation at $.path: msg (validator=...)'.
    A standalone (~12 lines) helper per the project's 'small enough to duplicate'
    convention — avoids a skills/ -> framework/ cross-package import with no other
    consumer."""
    head = errors[:3]
    tail = len(errors) - len(head)
    lines = []
    for e in head:
        path = "$" + "".join(
            f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in e.absolute_path
        )
        lines.append(
            f"schema violation at {path}: {e.message} (validator={e.validator})"
        )
    if tail > 0:
        lines.append(f"+{tail} more")
    return "; ".join(lines)


def _obs_name(value: str, module: str) -> str:
    """Strip the canonical txn wrapper to recover the agent name. Mirrors simulation render-scaffold's
    consume-side strip EXACTLY (same global .replace) so the gate accepts/rejects precisely
    what the consumer resolves. Known, accepted limitation (mirrored on both sides): an agent
    name that itself contains the module prefix or '_txn' is mangled — such names are
    pathological, and the gate rejects the unresolved result loudly. A hand-written oracle
    test pins the normal-case behavior."""
    return value.replace(f"{module}_", "").replace("_txn", "")


def semantic_errors(scaffold: dict) -> list:
    """Referential-integrity checks the JSON Schema cannot express: name uniqueness,
    compare_txn/inports/sequences.agent/tests.seqs/power_scenarios.sequence_ref resolution,
    and option-c (compare_txn omitted with multiple agents). Returns human-readable errors."""
    module = scaffold.get("module", "")
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
    cmp_txn = sb.get("compare_txn")
    if cmp_txn in (None, ""):
        if len(agents) > 1:
            errs.append(
                f"scoreboard.compare_txn omitted but {len(agents)} agents declared — ambiguous "
                f"observer (the scaffold would silently compare the last agent's stream). Name "
                f"the observer agent explicitly, e.g. '{module}_<agent>_txn'. "
                f"Agents: {sorted(n for n in agent_names if n)}."
            )
    else:
        obs = _obs_name(cmp_txn, module)
        if obs not in agent_names:
            errs.append(
                f"scoreboard.compare_txn {cmp_txn!r} resolves to agent {obs!r}, not in agents[] "
                f"{sorted(n for n in agent_names if n)}. It names the ONE observer agent whose "
                f"txn the scoreboard compares — not a DUT signal list or free description."
            )

    for txn in (scaffold.get("rm") or {}).get("inports", []):
        ag = _obs_name(txn, module)
        if ag not in agent_names:
            errs.append(
                f"rm.inports entry {txn!r} resolves to agent {ag!r}, not in agents[] "
                f"{sorted(n for n in agent_names if n)}. inports name the agent txns feeding the "
                f"RM — not reset/arbitrary signals."
            )

    for s in scaffold.get("sequences", []):
        ag = s.get("agent")
        if ag is not None and ag not in agent_names:
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
        if ref is not None and ref not in seq_names:
            errs.append(
                f"power_scenarios[{ps.get('id')!r}].sequence_ref {ref!r} not in sequences[] "
                f"{sorted(n for n in seq_names if n)}."
            )

    return errs


def coverage_errors(scaffold: dict, plan_data: dict) -> list:
    """Bidirectional coverage matrix: every plan-data check_id is covered (in some
    testpoints[].covers[]) or skipped (in skipped_checks[]); every non-empty covers[] entry
    resolves to a real plan-data check_id. The inline existence/non-emptiness is guaranteed by
    construction (the materialize-scaffold verb), so it is not re-checked here. The reverse
    (dangling-covers) check duplicates materialize's guard — it earns its keep only when
    check-scaffold runs standalone on a non-materialized scaffold; in the pipeline, materialize
    aborts on a dangling covers[] first."""
    check_ids = {
        h["check_id"] for h in plan_data.get("check_hints", []) if h.get("check_id")
    }
    covered, errs = set(), []
    for tp in scaffold.get("testpoints", []):
        for cid in tp.get("covers") or []:
            covered.add(cid)
            if cid not in check_ids:
                errs.append(
                    f"testpoint {tp.get('id')!r} covers references unknown check_id {cid!r} "
                    f"(not in plan-data check_hints)."
                )
    skipped = {s.get("check_id") for s in scaffold.get("skipped_checks", [])}
    uncovered = sorted(c for c in check_ids if c not in covered and c not in skipped)
    if uncovered:
        errs.append(
            f"uncovered check_hints: {uncovered} (cover each via testpoints[].covers[] or list "
            f"it in skipped_checks[] with a reason)."
        )
    return errs


def validate(scaffold: dict, schema: dict) -> list:
    """Return human-readable errors ([] if valid). Structural first; semantic only if
    structural passes (semantic assumes well-typed fields)."""
    validator = Draft202012Validator(schema)
    struct = sorted(
        validator.iter_errors(scaffold), key=lambda e: list(e.absolute_path)
    )
    if struct:
        return [_format_validation_errors(struct)]
    return semantic_errors(scaffold)


def run(scaffold_path, plan_data_path, schema_path=None) -> int:
    """check-scaffold: 3-layer gate (structural -> semantic -> coverage, short-circuit).
    exit 0 with 'check-scaffold: OK ...' / exit 1 with a fix-oriented message to stderr."""
    schema_path = Path(schema_path) if schema_path else _DEFAULT_SCHEMA
    scaffold = json.loads(Path(scaffold_path).read_text(encoding="utf-8"))
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    plan_data = json.loads(Path(plan_data_path).read_text(encoding="utf-8"))
    errors = validate(scaffold, schema)
    if not errors:
        errors = coverage_errors(scaffold, plan_data)
    if errors:
        sys.exit(
            "check-scaffold: scaffold-specification.json invalid:\n  - "
            + "\n  - ".join(errors)
            + "\nFix scaffold-specification.json (re-author per SKILL.md scaffold-spec contract) and re-run."
        )
    print(
        f"check-scaffold: OK ({len(scaffold.get('agents', []))} agents, "
        f"{len(scaffold.get('sequences', []))} sequences)"
    )
    return 0
