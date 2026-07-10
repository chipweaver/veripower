# tests/unit/test_spec_result.py
import json
import shutil
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "specification" / "scripts"))
from spec import constraints, result  # noqa: E402

_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"
_FIX = Path(__file__).resolve().parent / "fixtures" / "specification-tpu_top"

_CLEAR_REVIEW = {
    "schema_version": 1,
    "stage": "specification",
    "module": "m",
    "reviewed_children": ["mac"],
    "verdict": "ok",
    "has_critical": False,
    "findings": [],
}


def _design(io_rows, clk_rows):
    return (
        "# m Design\n\n#### 1.4.1 Top-Level IO\n\n"
        "| Signal | Direction | Width | Clock Domain | Interface Group | Protocol | Role | ResetPolarity | ResetKind |\n"
        "|---|---|---|---|---|---|---|---|---|\n" + io_rows + "\n"
        "### 1.6 Clocks and Frequencies\n\n"
        "| Clock Name | Nominal Frequency (MHz) | SDC Period (ns) | Relationship | Generated | Role |\n"
        "|---|---|---|---|---|---|\n" + clk_rows + "\n"
    )


def _spec_workdir(tmp_path):
    """A workdir derive_constraints() can run over (valid §1.6 + §1.4.1 tables) plus the
    finalize inputs (manifest/coverage/per-child md/spec-review)."""
    wd = tmp_path
    design = _design(
        "| i_clk | input | 1 | i_clk | clk | - | clock | - | - |\n",
        "| i_clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    (wd / "design.md").write_text(design)
    (wd / "manifest.json").write_text(
        json.dumps(
            {
                "module": "tpu_top",
                "children": [{"name": "mac", "doc": "mac.md", "rtl_modules": ["mac"]}],
            }
        )
    )
    (wd / "coverage.json").write_text(json.dumps({"status": "pass"}))
    (wd / "mac.md").write_text("# child\n")
    (wd / "spec-review.json").write_text(json.dumps(_CLEAR_REVIEW))
    return wd


def _validate_envelope(env: dict) -> None:
    env_schema = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (ROOT / "skills/specification/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        _ENVELOPE_URI, Resource.from_contents(env_schema)
    )
    Draft202012Validator(stage_schema, registry=registry).validate(
        env
    )  # raises on invalid


def test_build_result_pass_lean_shape(tmp_path):
    wd = _spec_workdir(tmp_path)
    assert (
        result.build_result(
            wd, module="tpu_top", ppa_targets=[], waived=[], status="pass"
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "specification",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["top_module"] == "tpu_top" and ss["ppa_targets"] == []
    assert ss["spec_gate"] == {
        "gate": "clear",
        "flagged": [],
        "must_ack": [],
        "waived": [],
    }
    assert "notes" not in ss and "fail_reason" not in ss  # lean shape
    assert json.loads((wd / "ppa.json").read_text()) == []  # sidecar written on pass
    assert {"path": "ppa.json", "kind": "ppa"} in env["artifacts"]


def test_build_result_passes_ppa_targets_through(tmp_path):
    wd = _spec_workdir(tmp_path)
    targets = [
        {"dim": "area_um2", "target": 70000.0},
        {"dim": "power_mw", "target": 12.5},
    ]
    result.build_result(
        wd, module="tpu_top", ppa_targets=targets, waived=[], status="pass"
    )
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert (
        ss["ppa_targets"] == targets
    )  # verbatim — orchestrate._ppa_targets reads this
    # ppa.json is the stable sidecar synthesis/power-analysis read directly (spec §4.3)
    assert json.loads((wd / "ppa.json").read_text()) == targets


def test_build_result_reject_status_writes_fail(tmp_path):
    # the human REJECTED at the Step-8 gate -> --status fail, gate still clear.
    wd = _spec_workdir(tmp_path)
    assert (
        result.build_result(
            wd, module="tpu_top", ppa_targets=[], waived=[], status="fail"
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail" and env["stage_specific"]["fail_reason"]


# ── artifacts[] enumeration tests (Task 3) ─────────────────────────────────
def test_enumerate_artifacts_present_only_with_kinds(tmp_path):
    wd = _spec_workdir(tmp_path)
    constraints.derive_constraints(
        wd
    )  # generate constraints/tpu_top.{sdc,sgdc} so they are present
    (wd / "fifo.md").write_text("# child\n")
    m = json.loads((wd / "manifest.json").read_text())
    m["children"].append({"name": "fifo", "doc": "fifo.md", "rtl_modules": ["fifo"]})
    (wd / "manifest.json").write_text(json.dumps(m))
    arts = result.enumerate_artifacts(wd, top="tpu_top")
    by_path = {a["path"]: a.get("kind") for a in arts}
    assert by_path["design.md"] == "design"
    assert by_path["manifest.json"] == "manifest"
    assert by_path["coverage.json"] == "coverage"
    assert by_path["spec-review.json"] == "spec-review"
    assert by_path["mac.md"] == "child-design" and by_path["fifo.md"] == "child-design"
    assert by_path["constraints/tpu_top.sdc"] == "sdc"
    assert by_path["constraints/tpu_top.sgdc"] == "sgdc"
    assert "brainstorm.md" not in by_path and "result.json" not in by_path
    assert all((wd / p).is_file() for p in by_path)  # present-only


# ── golden test against the real tpu_top run (lean shape + γ-floor + schema) ─


def test_golden_lean_against_real_tpu_top(tmp_path):
    wd = tmp_path / "specification"
    shutil.copytree(_FIX, wd)
    targets = [{"dim": "area_um2", "target": 70000.0}]
    # γ-floor: agent relays the human-gate outcome (approve, no waivers, PPA from D6).
    assert (
        result.build_result(
            wd, module="tpu_top", ppa_targets=targets, waived=[], status="pass"
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "pass"
    assert ss["top_module"] == "tpu_top"  # == manifest.module
    assert ss["ppa_targets"] == targets  # passed through verbatim
    assert ss["spec_gate"] == {
        "gate": "clear",
        "flagged": [],
        "must_ack": [],
        "waived": [],
    }
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {
        "design.md",
        "manifest.json",
        "coverage.json",
        "spec-review.json",
        "mac.md",
        "systolic_reg.md",
        "fifo.md",
        "tpu_top.md",
        "constraints/tpu_top.sdc",
        "constraints/tpu_top.sgdc",
        "ppa.json",
    }
    assert "brainstorm.md" not in paths and "result.json" not in paths
    assert "notes" not in ss
    assert env["produced_at"].endswith("Z")
    assert json.loads((wd / "ppa.json").read_text()) == targets
    _validate_envelope(env)


def test_golden_waived_flagged_finding_passes(tmp_path):
    # γ-floor: a flagged finding the human WAIVED -> the approve precondition is satisfied.
    wd = tmp_path / "specification"
    shutil.copytree(_FIX, wd)
    (wd / "spec-review.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": "specification",
                "module": "tpu_top",
                "reviewed_children": ["mac"],
                "verdict": "concerns",
                "has_critical": True,
                "findings": [
                    {
                        "child": "mac",
                        "lens": "faithfulness",
                        "severity": "critical",
                        "location": "§1.3",
                        "summary": "missing feature",
                    }
                ],
            }
        )
    )
    waived = [
        {
            "child": "mac",
            "lens": "faithfulness",
            "location": "§1.3",
            "classification": "accepted-risk",
            "reason": "out of scope this tapeout",
        }
    ]
    assert (
        result.build_result(
            wd, module="tpu_top", ppa_targets=[], waived=waived, status="pass"
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"  # waived -> precondition met
    assert (
        env["stage_specific"]["spec_gate"]["gate"] == "trip"
    )  # gate still reflects reality
    assert env["stage_specific"]["spec_gate"]["waived"] == waived
    _validate_envelope(env)


def test_golden_unwaived_flagged_blocks_pass(tmp_path):
    # the same flagged finding with NO waiver + --status pass -> finalize downgrades to fail.
    wd = tmp_path / "specification"
    shutil.copytree(_FIX, wd)
    (wd / "spec-review.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": "specification",
                "module": "tpu_top",
                "reviewed_children": ["mac"],
                "verdict": "concerns",
                "has_critical": True,
                "findings": [
                    {
                        "child": "mac",
                        "lens": "faithfulness",
                        "severity": "critical",
                        "location": "§1.3",
                        "summary": "missing feature",
                    }
                ],
            }
        )
    )
    result.build_result(wd, module="tpu_top", ppa_targets=[], waived=[], status="pass")
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert "approve precondition unmet" in env["stage_specific"]["fail_reason"]


def test_finalize_bad_ppa_targets_json_is_blocked(tmp_path):
    MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(tmp_path),
            "--module",
            "m",
            "--status",
            "pass",
            "--ppa-targets",
            "{not json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert "not valid JSON" in r.stderr


def test_finalize_missing_required_flag_is_blocked(tmp_path):
    MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2  # argparse: missing --module/--status
