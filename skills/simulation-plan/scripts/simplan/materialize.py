"""The materialize-scaffold verb — fill tb-scaffold.json from the spec sidecars.

Which fields it injects, and that they are never hand-authored, is on each field in
references/tb-scaffold.schema.json. What is not visible there:

- Clock/reset signals stay in interface.signals but are excluded from transaction.fields.
  A rand txn field driving the clock would fight the bench's own clock generator.
- Every injection is a verbatim copy, never an abstraction: the LLM authoring covers[] and
  interface_groups is the only judgment in the loop, and a renamed signal or a paraphrased
  check would break the `===` comparison the downstream refmodel is built to make.
- Pairs with simulation's scaffold renderer, which consumes interface.signals /
  transaction.fields via its _agent_io() helper.
"""

import json
import sys
from pathlib import Path

from simplan._plan import SCAFFOLD_NAME
from simplan.hints import HintsError, load_check_hints


def _clk_rst_signal_names(ports: list) -> set:
    """Names of the clock/reset ports. `role` is a schema enum, so an absent or bogus value
    cannot reach here — top-io.json is validated upstream."""
    return {s["name"] for s in ports if s.get("role") in {"clock", "reset"}}


def _derive_primary_clock(clocks: list) -> dict:
    primary = next((c for c in clocks if c.get("relationship") == "primary"), None)
    if primary is None:
        sys.exit(
            "materialize-scaffold: no clocks.json entry with relationship=='primary' — "
            "refusing to pick entry 0 as the TB main clock. Re-run specification."
        )
    return {"dut_port_name": primary["name"], "period_ns": primary["period_ns"]}


def _derive_reset(ports: list) -> dict:
    for s in ports:
        if s.get("role") == "reset":
            return {"dut_port_name": s["name"]}
    sys.exit(
        "materialize-scaffold: no top-io.json entry with role=='reset' — "
        "reset.dut_port_name cannot be derived. Re-run specification."
    )


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
    exclude = _clk_rst_signal_names(ports)
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
        matched = [s for g in groups for s in by_group[g]]
        matched_names = [s["name"] for s in matched]
        dupe_names = sorted({n for n in matched_names if matched_names.count(n) > 1})
        if dupe_names:
            sys.exit(
                f"materialize-scaffold: agent {aname!r} has duplicate signal name(s) "
                f"{dupe_names} across its interface_groups {groups} — would emit duplicate "
                f"SV declarations."
            )
        signals = [
            {
                "name": s["name"],
                "width": s["width"],
            }
            for s in matched
        ]
        agent["interface"] = {"signals": signals}
        agent["transaction"] = {
            "fields": [
                {
                    "name": sig["name"],
                    "width": sig["width"],
                    "type": "logic",
                    "rand": True,
                }
                for sig in signals
                if sig["name"] not in exclude
            ]
        }

    scaffold["primary_clock"] = _derive_primary_clock(clocks)
    scaffold["reset"] = _derive_reset(ports)
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
