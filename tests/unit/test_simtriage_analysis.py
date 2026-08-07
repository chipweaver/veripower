"""simtriage `finalize`: schema-gates the analysis judgment against the stage_specific
subschema folded (Task C7) into references/result.schema.json, then atomically writes
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
    """Task C7 Step 1: the standalone analysis.schema.json is deleted; the merge is the
    single source of truth from here on."""
    assert not (
        ROOT / "skills/simulation-triage/references/analysis.schema.json"
    ).exists()


def test_minimal_complete_accepted(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {
                "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design"}],
            },
        },
    )
    assert r.returncode == 0, r.stderr


def test_minimal_complete_writes_result_json_with_envelope(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {
                "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design"}],
            },
        },
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((tmp_path / "result.json").read_text())
    assert env["stage"] == "simulation-triage"
    assert env["status"] == "pass"
    assert env["artifacts"] == []
    assert env["stage_specific"] == {
        "analysis_state": "complete",
        "advisory": {
            "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design"}],
        },
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


def test_valid_skipped_derives_status_fail(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "skipped",
            "skipped_reason": "input incomplete: no fail_reason",
        },
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((tmp_path / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["analysis_state"] == "skipped"


def test_missing_analysis_state_exits_nonzero_no_write(tmp_path):
    r = _run(tmp_path, {"advisory": {"findings": []}})
    assert r.returncode == 1
    assert "analysis_state" in r.stderr
    assert not (tmp_path / "result.json").exists()


def test_complete_without_findings_exits_nonzero(tmp_path):
    """The attribution lives on the findings now, so a complete analysis with none has not
    said whose fault it is."""
    r = _run(tmp_path, {"analysis_state": "complete"})
    assert r.returncode == 1
    assert "advisory" in r.stderr or "findings" in r.stderr


def test_finding_without_root_cause_exits_nonzero(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {"findings": [{"anchor": "a.v:1"}]},
        },
    )
    assert r.returncode == 1
    assert "root_cause" in r.stderr


def test_complete_finding_without_anchor_exits_nonzero(tmp_path):
    """The anchor is what the fix owner opens this record for — the diagnosis names the
    rule, this file names the line — so a complete analysis must never be missing one."""
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {"findings": [{"root_cause": "rtl-design"}]},
        },
    )
    assert r.returncode == 1
    assert "anchor" in r.stderr


def test_skipped_without_reason_exits_nonzero(tmp_path):
    r = _run(tmp_path, {"analysis_state": "skipped"})
    assert r.returncode == 1
    assert "skipped_reason" in r.stderr


def test_root_cause_outside_enum_exits_nonzero(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {"findings": [{"anchor": "a.v:1", "root_cause": "synthesis"}]},
        },
    )
    assert r.returncode == 1


def test_unknown_top_level_key_rejected_by_additional_properties_false(tmp_path):
    payload = {
        "analysis_state": "complete",
        "groups": [{"fault_type": "x"}],
    }
    r = _run(tmp_path, payload)
    assert r.returncode == 1
    assert "groups" in r.stderr or "additional" in r.stderr.lower()


def test_advisory_tier_label_rejected(tmp_path):
    """`advisory.level` is gone: an experiment block is present exactly when one was built,
    and a label the same author writes one line from the data it labels gated nothing —
    omitting it or downgrading it both passed the requirement it was supposed to enforce."""
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {
                "level": "L2",
                "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design"}],
            },
        },
    )
    assert r.returncode == 1
    assert "level" in r.stderr


def test_prose_names_no_advisory_key_the_schema_rejects():
    """advisory is additionalProperties:false, so prose that instructs writing a key the schema
    dropped costs the agent a rejected finalize. Both surviving mentions of the deleted
    `waveform.observation` were exactly that; this pins the whole class."""
    advisory = _stage_specific()["properties"]["advisory"]
    legal = set(advisory["properties"])
    for sub, node in advisory["properties"].items():
        legal |= {f"{sub}.{k}" for k in node.get("properties", {})}

    skill_dir = ROOT / "skills/simulation-triage"
    docs = [skill_dir / "SKILL.md", *sorted(skill_dir.glob("references/*.md"))]
    cited: set[str] = set()
    for doc in docs:
        text = doc.read_text()
        for body in re.findall(r"advisory\.\{([^}]*)\}", text):
            cited |= {t.strip().rstrip("[]") for t in body.split(",") if t.strip()}
        for tok in re.findall(r"advisory\.([A-Za-z_]+(?:\.[A-Za-z_]+)?)", text):
            cited.add(tok)

    assert cited, "no advisory.* citation found — did the prose stop naming the shape?"
    assert cited <= legal, (
        f"prose names advisory key(s) absent from result.schema.json: "
        f"{sorted(cited - legal)}"
    )


def test_advisory_unknown_key_rejected(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {"bogus": 1},
        },
    )
    assert r.returncode == 1


def test_advisory_old_repro_key_rejected(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {"repro": {"tool": "verilator"}},
        },
    )
    # 'repro' renamed to 'experiment'; additionalProperties:false rejects it
    assert r.returncode == 1


def test_advisory_findings_valid(tmp_path):
    r = _run(
        tmp_path,
        {
            "analysis_state": "complete",
            "advisory": {
                "findings": [
                    {
                        "anchor": "fp_pkg.svh:264",
                        "cases": ["T-E2E"],
                        "root_cause": "rtl-design",
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
            "advisory": {
                "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design"}],
                "waveform": {
                    "commands": [
                        "fsdbreport T-SMOKE.fsdb -s /fa_tb_top/u_dut/scores_S -bt 40ns -et 80ns -of h"
                    ],
                    "signals": ["/fa_tb_top/u_dut/scores_S"],
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
            "advisory": {
                "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design"}],
                "experiment": {
                    "tool": "verilator",
                    "stimulus": "hand-picked fp32_add operand pairs 2+(-3),4+(-5)",
                    "artifacts": ["experiment/tb_add.sv"],
                    "golden": "golden_fa.py",
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
                "advisory": {
                    "findings": [{"anchor": "a.v:1", "root_cause": "rtl-design"}],
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
