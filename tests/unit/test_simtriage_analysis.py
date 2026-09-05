"""simtriage `finalize`: schema-gates the analysis judgment against the stage_specific
subschema folded into references/result.schema.json, then atomically writes
result.json. Supersedes the old validate-analysis-against-analysis.schema.json test:
analysis.schema.json is deleted, and there is no more analysis.json + top-level pointer —
result.json is the single output surface."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-triage/scripts/simtriage/__main__.py"
RESULT_SCHEMA = ROOT / "skills/simulation-triage/references/result.schema.json"


def _stage_specific() -> dict:
    doc = json.loads(RESULT_SCHEMA.read_text())
    for sub in doc["allOf"]:
        if "stage_specific" in sub.get("properties", {}):
            return sub["properties"]["stage_specific"]
    raise AssertionError("result.schema.json: no stage_specific subschema found")


def _run(tmp_path, payload: dict, *, workdir=None):
    argv = [
        sys.executable,
        str(MAIN),
        "finalize",
        "--workdir",
        str(workdir or tmp_path),
        "--json-stdin",
    ]
    return subprocess.run(
        argv, input=json.dumps(payload), capture_output=True, text=True
    )


def test_result_schema_has_no_standalone_analysis_schema_file():
    """Step 1: the standalone analysis.schema.json is deleted; the merge is the
    single source of truth from here on."""
    assert not (
        ROOT / "skills/simulation-triage/references/analysis.schema.json"
    ).exists()


def test_minimal_complete_accepted(tmp_path):
    r = _run(
        tmp_path,
        {
            "findings": [
                {"anchor": "a.v:1", "root_cause": "rtl-design", "reason": "why"}
            ],
        },
    )
    assert r.returncode == 0, r.stderr


def test_minimal_complete_writes_result_json_with_envelope(tmp_path):
    r = _run(
        tmp_path,
        {
            "findings": [
                {"anchor": "a.v:1", "root_cause": "rtl-design", "reason": "why"}
            ],
        },
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((tmp_path / "result.json").read_text())
    assert env["stage"] == "simulation-triage"
    assert env["status"] == "pass"
    assert env["artifacts"] == []
    assert env["stage_specific"] == {
        "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design", "reason": "why"}]
    }
    # the written file itself validates against the full merged schema
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    envelope = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    registry = Registry().with_resource(
        "https://veripower.local/schemas/envelope.schema.json",
        Resource.from_contents(envelope, default_specification=DRAFT202012),
    )
    jsonschema.Draft202012Validator(
        json.loads(RESULT_SCHEMA.read_text()), registry=registry
    ).validate(env)


def test_no_attribution_derives_status_fail(tmp_path):
    r = _run(
        tmp_path,
        {"findings": [], "reason": "input incomplete: no fail_reason"},
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((tmp_path / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["findings"] == []


def test_missing_findings_exits_nonzero_no_write(tmp_path):
    r = _run(tmp_path, {"reason": "x"})
    assert r.returncode == 1
    assert "findings" in r.stderr
    assert not (tmp_path / "result.json").exists()


def test_finding_without_root_cause_exits_nonzero(tmp_path):
    r = _run(tmp_path, {"findings": [{"anchor": "a.v:1", "reason": "why"}]})
    assert r.returncode == 1
    assert "root_cause" in r.stderr


def test_finding_without_anchor_exits_nonzero(tmp_path):
    """The anchor is where the fix owner starts — the diagnosis names the rule, this file
    names the line — so a finding must never be missing one."""
    r = _run(tmp_path, {"findings": [{"root_cause": "rtl-design", "reason": "why"}]})
    assert r.returncode == 1
    assert "anchor" in r.stderr


def test_finding_without_reason_exits_nonzero(tmp_path):
    """This file is the whole account the fix owner is handed. A finding with no argument is
    a coordinate it cannot check, and it will act on it anyway."""
    r = _run(tmp_path, {"findings": [{"anchor": "a.v:1", "root_cause": "rtl-design"}]})
    assert r.returncode == 1
    assert "reason" in r.stderr


def test_no_attribution_without_reason_exits_nonzero(tmp_path):
    r = _run(tmp_path, {"findings": []})
    assert r.returncode == 1
    assert "reason" in r.stderr


def test_root_cause_outside_enum_exits_nonzero(tmp_path):
    r = _run(
        tmp_path,
        {"findings": [{"anchor": "a.v:1", "root_cause": "synthesis", "reason": "why"}]},
    )
    assert r.returncode == 1


def test_unknown_top_level_key_rejected_by_additional_properties_false(tmp_path):
    r = _run(tmp_path, {"findings": [], "reason": "x", "groups": [{"fault_type": "x"}]})
    assert r.returncode == 1
    assert "groups" in r.stderr or "additional" in r.stderr.lower()


def test_prose_names_no_stage_specific_key_the_schema_rejects():
    """stage_specific is additionalProperties:false, so prose that instructs writing a key the
    schema dropped costs the agent a rejected finalize. This pins the whole class."""
    ss = _stage_specific()
    legal = set(ss["properties"])
    legal |= set(ss["properties"]["findings"]["items"]["properties"])

    skill_dir = ROOT / "skills/simulation-triage"
    docs = [skill_dir / "SKILL.md", *sorted(skill_dir.glob("references/*.md"))]
    cited: set[str] = set()
    for doc in docs:
        for tok in re.findall(r'"([a-z_]+)":', doc.read_text()):
            cited.add(tok)

    assert cited, "no JSON key citation found — did the prose stop naming the shape?"
    assert cited <= legal, (
        f"prose names stage_specific key(s) absent from result.schema.json: "
        f"{sorted(cited - legal)}"
    )


def test_json_file_input(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "findings": [
                    {"anchor": "a.v:1", "root_cause": "rtl-design", "reason": "why"}
                ]
            }
        )
    )
    r = subprocess.run(
        [
            sys.executable,
            str(MAIN),
            "finalize",
            "--workdir",
            str(tmp_path),
            "--json-file",
            str(p),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "result.json").is_file()


def test_invalid_json_exits_blocked_not_written(tmp_path):
    r = subprocess.run(
        [
            sys.executable,
            str(MAIN),
            "finalize",
            "--workdir",
            str(tmp_path),
            "--json-stdin",
        ],
        input="{not json",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert "not valid JSON" in r.stderr
    assert not (tmp_path / "result.json").exists()
