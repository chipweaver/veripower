"""Cross-stage producer/consumer contract checks (D3).

Two invariants that prevent silent-transformation drift across stage
boundaries:

1. **PPA dim namespace consistency.** Every `dim` value that any stage's
   `ppa_actual[]` schema allows (via const or enum) must appear in
   `specification.ppa_targets[].dim` enum. specification authors the
   targets; downstream stages MEASURE against them. A stage that reports
   a dim specification can't express has no target — convergence routing
   loses signal silently.

2. **result.json path consistency.** Every `(Design|Verification)/<stage>/
   result.json` reference in any SKILL.md must match the (dir, stage)
   tuple in `topology._RESULT_DIR`. A SKILL.md saying `Design/synthesis/`
   while state.py promotes to `Verification/synthesis/` is the canonical
   path-drift incident type the failure-memory entry flags.
"""

import re

import pytest
from _skills_sot import PLUGIN_ROOT, load_stage_schema

from framework.scripts.state import FORWARD_PRIORITY
from framework.scripts.topology import _RESULT_DIR


def _collect_dim_values_from_array_schema(array_schema: dict) -> set[str]:
    """Pull const/enum dim values out of an `items.properties.dim` slot.

    Returns an empty set for pattern-based dim definitions (e.g.
    timing-analysis violations use `pattern: ^timing_…$` which is a
    different namespace from PPA gate dims and shouldn't be checked
    against specification.ppa_targets).
    """
    dim_schema = array_schema.get("items", {}).get("properties", {}).get("dim", {})
    if "const" in dim_schema:
        return {dim_schema["const"]}
    if "enum" in dim_schema:
        return set(dim_schema["enum"])
    return set()


def _ppa_actual_dims_for_stage(stage: str) -> set[str]:
    dims: set[str] = set()
    for entry in load_stage_schema(stage).get("allOf", []):
        ss = entry.get("properties", {}).get("stage_specific", {})
        ppa = ss.get("properties", {}).get("ppa_actual")
        if ppa:
            dims |= _collect_dim_values_from_array_schema(ppa)
    return dims


def _spec_ppa_target_dims() -> set[str]:
    for entry in load_stage_schema("specification").get("allOf", []):
        ss = entry.get("properties", {}).get("stage_specific", {})
        ppa_t = ss.get("properties", {}).get("ppa_targets")
        if ppa_t:
            return _collect_dim_values_from_array_schema(ppa_t)
    return set()


def test_ppa_dim_union_subset_of_spec_targets() -> None:
    """Every measured PPA dim must be a target dim specification can author."""
    measured: dict[str, set[str]] = {}
    for stage in FORWARD_PRIORITY:
        if stage == "specification":
            continue
        dims = _ppa_actual_dims_for_stage(stage)
        if dims:
            measured[stage] = dims

    measured_union: set[str] = set().union(*measured.values()) if measured else set()
    spec_targets = _spec_ppa_target_dims()
    missing = measured_union - spec_targets
    assert not missing, (
        f"Stages report ppa_actual dims {sorted(missing)} that specification's "
        f"ppa_targets[].dim enum doesn't list. Per-stage measured dims: "
        f"{ {s: sorted(d) for s, d in measured.items()} }; "
        f"spec target dims: {sorted(spec_targets)}. Add the missing dim(s) to "
        f"specification's ppa_targets enum, or stop reporting them downstream."
    )


_RESULT_PATH_RE = re.compile(
    r"\b(Design|Verification)/([a-z][a-z0-9-]*)/result\.json\b"
)


@pytest.mark.parametrize("skill_name", FORWARD_PRIORITY)
def test_result_path_references_match_state_dir(skill_name: str) -> None:
    """In each SKILL.md, every Design|Verification/<stage>/result.json
    citation must use the dir prefix topology._RESULT_DIR maps for that stage.
    """
    skill_md = PLUGIN_ROOT / "skills" / skill_name / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    drifts: list[tuple[str, str, str]] = []
    for m in _RESULT_PATH_RE.finditer(text):
        cited_dir, cited_stage = m.group(1), m.group(2)
        expected = _RESULT_DIR.get(cited_stage)
        if expected is None:
            drifts.append((cited_stage, cited_dir, "<unknown stage>"))
            continue
        if expected[0] != cited_dir:
            drifts.append((cited_stage, cited_dir, expected[0]))

    assert not drifts, f"SKILL.md {skill_name}: result.json path drift — " + "; ".join(
        f"cites {d}/{s}/result.json but topology._RESULT_DIR says {e}/{s}"
        for s, d, e in drifts
    )


def test_power_dut_path_matches_simulation_tb_top() -> None:
    """power's DUT scope must match simulation tb_top.sv's {{TOP}}_tb_top + u_dut SSoT."""
    sim_tb = (PLUGIN_ROOT / "skills" / "simulation" / "templates" / "scaffold"
              / "tb_top.sv").read_text(encoding="utf-8")
    assert "{{TOP}}_tb_top" in sim_tb, "simulation tb_top module-name convention drifted"
    assert re.search(r"\{\{TOP\}\}\s+u_dut\b", sim_tb), "simulation DUT instance name drifted from u_dut"

    pa = PLUGIN_ROOT / "skills" / "power-analysis" / "templates"
    env_sh = (pa / "env.sh").read_text(encoding="utf-8")
    assert 'DUT_INST="u_dut"' in env_sh, "power env.sh DUT_INST drifted from u_dut"
    assert 'TB_TOP="${TOP}_tb_top"' in env_sh, "power env.sh TB_TOP drifted from ${TOP}_tb_top"
    # power test template's toggle scope must use the same {TOP}_tb_top.u_dut convention.
    tmpl = (pa / "scaffold" / "power_test.sv.tmpl").read_text(encoding="utf-8")
    assert "{{TOP}}_tb_top.u_dut" in tmpl
    # ptpx.tcl must NOT hardcode the DUT path (S3: reads $STRIP_PATH, fail-loud if unset).
    ptpx = (pa / "scripts" / "ptpx.tcl").read_text(encoding="utf-8")
    assert "_tb_top/u_dut" not in ptpx, "ptpx.tcl still hardcodes the DUT strip_path (should read $STRIP_PATH)"
    assert "env(STRIP_PATH)" in ptpx, "ptpx.tcl must read strip_path from $STRIP_PATH (env.sh) — guard removed?"
