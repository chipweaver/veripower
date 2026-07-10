"""No skill-decided BLOCKED — schema-layer lock.

VeriPower architectural invariant: only state.py program-exception paths
emit BLOCKED-class sentinels. Skills emit `status ∈ {pass, fail}` in
result.json; simulation-triage emits `analysis_state ∈ {complete,
skipped}` in its ANALYSIS JSON.

Anchor: memory entry feedback_blocked_uniform_removal; original removal
d7e01d2 / 2bd3a6e / d0b16a0; canonical regression 34fc144
(simulation-triage SKILL.md instructing the agent to emit
`STATUS: BLOCKED <reason>` as a decision signal — purely textual, did
not touch schema). 31817a4 corrective added the analysis_state
discriminator to lock the invariant in schema form.

Scope: this lint covers the *schema layer* only. SKILL.md text-layer
regression (the 34fc144 form) is review-detected, not statically
lintable.
"""

import json

from _skills_sot import PLUGIN_ROOT


def test_envelope_status_enum_is_pass_fail():
    """envelope.schema.json's status field accepts only pass or fail."""
    schema_path = (
        PLUGIN_ROOT / "framework" / "references" / "schemas" / "envelope.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["status"]["enum"] == ["pass", "fail"], (
        f"envelope.schema.json status.enum drifted: {schema['properties']['status']['enum']}. "
        "Only state.py program-exception paths may emit BLOCKED-class sentinels; "
        "see memory feedback_blocked_uniform_removal."
    )


def test_simulation_triage_analysis_state_enum_is_canonical():
    """simulation-triage's analysis_state discriminator is complete | skipped only.

    Task C7 folded the standalone analysis.schema.json into
    result.schema.json's stage_specific subschema — the invariant lives
    there now (same canonical enum)."""
    schema_path = (
        PLUGIN_ROOT
        / "skills"
        / "simulation-triage"
        / "references"
        / "result.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    stage_specific = next(
        sub["properties"]["stage_specific"]
        for sub in schema["allOf"]
        if "stage_specific" in sub.get("properties", {})
    )
    enum = stage_specific["properties"]["analysis_state"]["enum"]
    assert enum == ["complete", "skipped"], (
        f"result.schema.json stage_specific.analysis_state.enum drifted: {enum}. "
        "Reintroducing 'blocked' here would re-enable skill-decided BLOCKED — the 34fc144 regression class. "
        "31817a4 added this discriminator specifically to lock the invariant in schema form."
    )
