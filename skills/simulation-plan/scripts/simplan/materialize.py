"""The materialize-scaffold verb — fill tb-scaffold.json from the spec sidecars.

Which fields it injects, and that they are never hand-authored, is on each field in
references/tb-scaffold.schema.json. What is not visible there:

- What the DUT looks like is NOT injected. Signals, clocks and the reset polarity are read
  from top-io.json / clocks.json by simulation itself, at render time. A stored copy could
  disagree with the source after either moved, and had no totality — a port absent from it
  rendered as a DUT port bound to nothing. What this verb still checks is the assignment the
  plan author made: that every agent's interface_groups resolve, and hold data ports.
- Every injection that remains is a verbatim copy, never an abstraction: the LLM authoring
  covers[] and interface_groups is the only judgment in the loop, and a paraphrased check
  would break the `===` comparison the downstream refmodel is built to make.
"""

import json
import sys
from pathlib import Path

from simplan._plan import SCAFFOLD_NAME
from simplan.hints import HintsError, load_check_hints


def _materialize_inline(check_hints: list, scaffold: dict) -> None:
    """Fill testpoints[].inlined_check_hints[] deterministically from covers[] + the hints.
    implementation_detail = prefer(verbatim, summary). Fails loud on a covers[] check_id absent
    from the hints (also the gate's reverse check). LLM authors covers[] (clustering) only."""
    by_id = {h["check_id"]: h for h in check_hints if h.get("check_id")}
    for tp in scaffold.get("testpoints", []):
        inlined = []
        for cid in tp.get("covers") or []:
            h = by_id.get(cid)
            if h is None:
                sys.exit(
                    f"materialize-scaffold: testpoint {tp.get('id')!r} covers unknown check_id "
                    f"{cid!r} (not in the authored check hints). Known: {sorted(by_id)}."
                )
            detail = (h.get("implementation_detail_verbatim") or "").strip() or (
                h.get("implementation_detail") or ""
            ).strip()
            entry = {
                "check_id": cid,
                "implementation_detail": detail,
            }
            for opt in ("observable", "reference_rule", "latency", "reset_behavior"):
                v = (h.get(opt) or "").strip()
                if v:
                    entry[opt] = v
            inlined.append(entry)
        tp["inlined_check_hints"] = inlined


def _inject_feature_names(scaffold: dict, features: list) -> None:
    """Resolve each test's feature id to the authored features.json name.

    An unresolvable id is a plan defect, not a missing optional: the Feature column of
    case-results-summary.md is generated from this, and a bare id there is what this
    injection exists to prevent.
    """
    by_id = {f["id"]: f["name"] for f in features if f.get("id")}
    for test in scaffold.get("tests", []):
        fid = (test.get("feature") or "").strip()
        if not fid:
            sys.exit(
                f"materialize-scaffold: test {test.get('name', '<unnamed>')!r} has no "
                f"'feature'. Every test names the features.json id it exercises."
            )
        if fid not in by_id:
            sys.exit(
                f"materialize-scaffold: test {test.get('name', '<unnamed>')!r} references "
                f"unknown feature {fid!r}. Valid ids in features.json: {sorted(by_id)}."
            )
        test["feature_name"] = by_id[fid]


def materialize(
    check_hints: list, scaffold: dict, clocks: list, ports: list, features: list
) -> dict:
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

    _materialize_inline(check_hints, scaffold)
    _inject_feature_names(scaffold, features)
    return scaffold


def run(plan_dir, spec_workdir) -> int:
    """One --spec path instead of one per sidecar: they all live in the specification
    workdir, and the list would otherwise grow with every sidecar added.

    Reads tb-scaffold.json raw rather than through _plan.load_plan: this verb runs BEFORE
    check-scaffold, on a file that does not validate yet (the fields it injects are the
    schema's own required ones), and it touches nothing in the other two sidecars.
    """
    spec = Path(spec_workdir)
    scaffold_path = Path(plan_dir) / SCAFFOLD_NAME
    try:
        scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"materialize-scaffold: {scaffold_path} not found.")
    except json.JSONDecodeError as e:
        sys.exit(f"materialize-scaffold: {scaffold_path} is not valid JSON: {e}")
    sidecars = {}
    for name in ("clocks.json", "top-io.json", "features.json"):
        path = spec / name
        try:
            sidecars[name] = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            sys.exit(f"materialize-scaffold: {path} not found; check the --spec path.")
        except json.JSONDecodeError as e:
            sys.exit(f"materialize-scaffold: {path} is not valid JSON: {e}")
    try:
        check_hints = load_check_hints(spec)
    except HintsError as e:
        sys.exit(f"materialize-scaffold: {e}")
    scaffold = materialize(
        check_hints,
        scaffold,
        sidecars["clocks.json"],
        sidecars["top-io.json"],
        sidecars["features.json"],
    )
    scaffold_path.write_text(
        json.dumps(scaffold, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"materialize-scaffold: materialized {len(scaffold.get('agents', []))} agent(s) "
        f"from {spec}"
    )
    return 0
