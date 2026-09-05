"""No skill-decided BLOCKED — schema-layer lock.

VeriPower architectural invariant: only kernel.py program-exception paths
emit BLOCKED-class sentinels. Skills emit `status ∈ {pass, fail}` in
result.json.

Scope: this lint covers the *schema layer* only — the enum itself. SKILL.md
text-layer regression (a skill instructing its agent to emit
`STATUS: BLOCKED` as a decision rather than as a crash) is review-detected,
not statically lintable.
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
        "Only kernel.py program-exception paths may emit BLOCKED-class sentinels; "
        "see memory feedback_blocked_uniform_removal."
    )
