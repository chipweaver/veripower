"""simtriage `finalize`: schema-gates the analysis judgment against the stage_specific
subschema folded (Task C7) into references/result.schema.json, then atomically writes
result.json. Supersedes the old validate-analysis-against-analysis.schema.json test:
analysis.schema.json is deleted, and there is no more analysis.json + top-level pointer —
result.json is the single output surface."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-triage/scripts/simtriage/__main__.py"
RESULT_SCHEMA = ROOT / "skills/simulation-triage/references/result.schema.json"


def _stage_specific_schema() -> dict:
    doc = json.loads(RESULT_SCHEMA.read_text())
    for sub in doc["allOf"]:
        props = sub.get("properties", {})
        if "stage_specific" in props:
            return props["stage_specific"]
    raise AssertionError("result.schema.json: no stage_specific subschema found")


def _run(tmp_path, payload: dict, *, schema=None, workdir=None, module="M"):
    wd = workdir or tmp_path
    argv = [
        sys.executable,
        str(MAIN),
        "finalize",
        "--workdir",
        str(wd),
        "--module",
        module,
        "--json-stdin",
    ]
    if schema is not None:
        argv += ["--schema", str(schema)]
    return subprocess.run(
        argv, input=json.dumps(payload), capture_output=True, text=True
    )


def test_result_schema_has_no_standalone_analysis_schema_file():
    """Task C7 Step 1: the standalone analysis.schema.json is deleted; the merge is the
    single source of truth from here on."""
    assert not (
        ROOT / "skills/simulation-triage/references/analysis.schema.json"
    ).exists()


def test_default_schema_used_when_flag_omitted(tmp_path):
    r = _run(
        tmp_path,
        {"analysis_state": "complete", "root_cause": "rtl-design", "confidence": "high",
         "advisory": {"level": "L1", "findings": [{"fault_type": "x", "anchor": "a.v:1"}]}},
    )
    assert r.returncode == 0, r.stderr


def test_explicit_schema_override_still_accepted(tmp_path):
    schema_path = tmp_path / "override.schema.json"
    schema_path.write_text(json.dumps(_stage_specific_schema()))
    r = _run(
        tmp_path,
        {"analysis_state": "complete", "root_cause": "rtl-design", "confidence": "high",
         "advisory": {"level": "L1", "findings": [{"fault_type": "x", "anchor": "a.v:1"}]}},
        schema=schema_path,
    )
    assert r.returncode == 0, r.stderr


def test_minimal_complete_writes_result_json_with_envelope(tmp_path):
    r = _run(
        tmp_path,
        {"analysis_state": "complete", "root_cause": "rtl-design", "confidence": "high",
         "advisory": {"level": "L1", "findings": [{"fault_type": "x", "anchor": "a.v:1"}]}},
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((tmp_path / "result.json").read_text())
    assert env["stage"] == "simulation-triage"
    assert env["module"] == "M"
    assert env["schema_version"] == 1
    assert env["status"] == "pass"
    assert env["artifacts"] == []
    assert env["stage_specific"] == {
        "analysis_state": "complete",
        "root_cause": "rtl-design",
        "confidence": "high",
        "advisory": {"level": "L1", "findings": [{"fault_type": "x", "anchor": "a.v:1"}]},
    }
    # the written file itself validates against the full merged schema
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    envelope = json.loads(
        (
            ROOT / "framework/references/schemas/envelope.schema.json"
        ).read_text()
    )
    registry = Registry().with_resource(
        "https://veripower.local/schemas/envelope.schema.json",
        Resource.from_contents(envelope, default_specification=DRAFT202012),
    )
    jsonschema.Draft202012Validator(
        json.loads(RESULT_SCHEMA.read_text()), registry=registry
    ).validate(env)


def test_valid_skipped_derives_status_fail(tmp_path):
    r = _run(
        tmp_path,
        {"analysis_state": "skipped", "skipped_reason": "input incomplete: failure_phase"},
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((tmp_path / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["analysis_state"] == "skipped"


def test_missing_analysis_state_exits_nonzero_no_write(tmp_path):
    r = _run(tmp_path, {"root_cause": "rtl-design"})
    assert r.returncode == 1
    assert "analysis_state" in r.stderr
    assert not (tmp_path / "result.json").exists()


def test_complete_without_root_cause_exits_nonzero(tmp_path):
    r = _run(tmp_path, {"analysis_state": "complete"})
    assert r.returncode == 1
    assert "root_cause" in r.stderr


def test_complete_without_confidence_exits_nonzero(tmp_path):
    r = _run(tmp_path, {"analysis_state": "complete", "root_cause": "rtl-design"})
    assert r.returncode == 1
    assert "confidence" in r.stderr


def test_skipped_without_reason_exits_nonzero(tmp_path):
    r = _run(tmp_path, {"analysis_state": "skipped"})
    assert r.returncode == 1
    assert "skipped_reason" in r.stderr


def test_root_cause_outside_enum_exits_nonzero(tmp_path):
    r = _run(tmp_path, {"analysis_state": "complete", "root_cause": "synthesis"})
    assert r.returncode == 1


def test_confidence_outside_enum_rejected(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "very-high",
        },
    )
    assert r.returncode == 1


def test_unknown_top_level_key_rejected_by_additional_properties_false(tmp_path):
    payload = {
        "analysis_state": "complete",
        "root_cause": "rtl-design",
        "confidence": "high",
        "groups": [{"fault_type": "x"}],
    }
    r = _run(tmp_path, payload)
    assert r.returncode == 1
    assert "groups" in r.stderr or "additional" in r.stderr.lower()


def test_advisory_unknown_key_rejected(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {"bogus": 1},
        },
    )
    assert r.returncode == 1


def test_advisory_old_repro_key_rejected(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {"repro": {"tool": "verilator"}},
        },
    )
    # 'repro' renamed to 'experiment'; additionalProperties:false rejects it
    assert r.returncode == 1


def test_advisory_findings_and_fix_direction_valid(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {
                "level": "L1",
                "fix_direction": "fp_pkg.svh::fp32_add: magnitude-compare in opposite-sign branch",
                "findings": [
                    {
                        "fault_type": "data_mismatch",
                        "anchor": "fp_pkg.svh:264",
                        "cases": ["T-E2E"],
                    }
                ],
            },
        },
    )
    assert r.returncode == 0, r.stderr


def test_advisory_waveform_valid(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {
                "level": "L1",
                "findings": [{"fault_type": "x", "anchor": "a.v:1"}],
                "waveform": {
                    "commands": [
                        "fsdbreport T-SMOKE.fsdb -s /fa_tb_top/u_dut/scores_S -bt 40ns -et 80ns -of h"
                    ],
                    "signals": ["/fa_tb_top/u_dut/scores_S"],
                    "observation": "scores_S frozen constant through MAX phase",
                },
            },
        },
    )
    assert r.returncode == 0, r.stderr


def test_advisory_experiment_valid(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
            "advisory": {
                "level": "L2",
                "findings": [{"fault_type": "x", "anchor": "a.v:1"}],
                "experiment": {
                    "tool": "verilator",
                    "stimulus": "hand-picked fp32_add operand pairs 2+(-3),4+(-5)",
                    "artifacts": ["experiment/tb_add.sv"],
                    "golden": "golden_fa.py",
                    "conclusion": "fp32_add eq-exp subtraction underflow confirmed",
                },
            },
        },
    )
    assert r.returncode == 0, r.stderr


def test_json_file_input(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "analysis_state": "complete",
                "root_cause": "rtl-design",
                "confidence": "high",
                "advisory": {
                    "level": "L1",
                    "findings": [{"fault_type": "x", "anchor": "a.v:1"}],
                },
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
            "--module",
            "M",
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
            "--module",
            "M",
            "--json-stdin",
        ],
        input="{not json",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert "not valid JSON" in r.stderr
    assert not (tmp_path / "result.json").exists()
