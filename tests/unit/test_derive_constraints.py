# tests/unit/test_derive_constraints.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/specification/scripts/derive_constraints.py"

sys.path.insert(0, str(ROOT / "skills" / "specification" / "scripts"))
import derive_constraints as dc  # noqa: E402


def _run(workdir, check=True):
    return subprocess.run(
        ["python3", str(SCRIPT), str(workdir)],
        capture_output=True,
        text=True,
        check=check,
    )


def _design(io_rows, clk_rows):
    return (
        "# m Design\n\n#### 1.4.1 Top-Level IO\n\n"
        "| Signal | Direction | Width | Clock Domain | Interface Group | Protocol | Role | ResetPolarity | ResetKind |\n"
        "|---|---|---|---|---|---|---|---|---|\n" + io_rows + "\n"
        "### 1.6 Clocks and Frequencies\n\n"
        "| Clock Name | Nominal Frequency (MHz) | SDC Period (ns) | Relationship | Generated | Role |\n"
        "|---|---|---|---|---|---|\n" + clk_rows + "\n"
    )


def _wd(tmp_path, design):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "m",
                "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
            }
        )
    )
    (tmp_path / "design.md").write_text(design)
    return tmp_path


def test_core_clocks_and_io_delays(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n"
        "| dout | output | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    summary = json.loads(_run(_wd(tmp_path, design)).stdout)
    assert summary == {"top": "m", "clocks": 1, "data_ports": 2, "resets": 0}
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "create_clock -name clk -period 10.0 [get_ports clk]" in sdc
    assert "set_input_delay  3.0 -clock clk [get_ports {din}]" in sdc
    assert "set_output_delay 3.0 -clock clk [get_ports {dout}]" in sdc
    assert "clock -name clk -period 10.0 -edge {0 5.0}" in sgdc
    assert "abstract_port -ports {din dout} -clock clk" in sgdc
    # data/clock split exact via Role: clk gets no IO delay
    assert "[get_ports {clk}]" not in sdc


def test_async_reset_emits_async_flag(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst_n | input | 1 | clk | reset | - | reset | 0 | async |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    summary = json.loads(_run(_wd(tmp_path, design)).stdout)
    assert summary["resets"] == 1
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name rst_n -value 0 -async" in sgdc
    assert "abstract_port -ports rst_n -clock clk -reset rst_n" in sgdc


def test_sync_reset_drops_async_flag(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst | input | 1 | clk | reset | - | reset | 1 | sync |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    _run(_wd(tmp_path, design))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name rst -value 1\n" in sgdc  # no -async
    assert "-async" not in sgdc.split("reset -name rst")[1].split("\n")[0]


def test_no_reset_ports_emits_no_reset_section(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    _run(_wd(tmp_path, design))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name" not in sgdc


def test_async_clock_groups(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| clk_io | input | 1 | clk_io | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_io | 50 | 20.0 | async | no | io clock |\n",
    )
    _run(_wd(tmp_path, design))
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_clock_groups -asynchronous" in sdc
    assert "-group [get_clocks {clk}]" in sdc
    assert "-group [get_clocks clk_io]" in sdc


def test_generated_clock_skips_create_clock(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_div2 | 50 | 20.0 | synchronous-related | yes | divider out |\n",
    )
    json.loads(_run(_wd(tmp_path, design)).stdout)
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "create_clock -name clk_div2" not in sdc
    assert "create_generated_clock clk_div2: deferred to RTL" in sdc
    assert (
        "create_clock -name clk -period 10.0" in sdc
    )  # the real top clock still emitted
    # SGDC symmetrically skips the generated clock
    assert "clock -name clk_div2" not in sgdc
    assert "clock -name clk -period 10.0 -edge {0 5.0}" in sgdc


def test_fail_loud_empty_clock_table(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n", ""
    )  # no clock rows
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "1.6" in proc.stderr


def test_fail_loud_invalid_role(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | bogus | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "Role" in proc.stderr


def test_fail_loud_reset_missing_kind(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst_n | input | 1 | clk | reset | - | reset | 0 | |\n"  # no ResetKind
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "ResetKind" in proc.stderr


def test_data_port_on_generated_clock_deferred(tmp_path):
    # A data port whose Clock Domain is a GENERATED clock is deferred to RTL
    # (create_generated_clock pin not yet known). generate_sdc/generate_sgdc skip it
    # by design, so the self-check mirrors that skip — it must NOT fail-loud demanding
    # an abstract_port the generators intentionally did not emit. Valid input → exit 0,
    # and no abstract_port is emitted for the deferred port.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| pgen | input | 8 | clk_div2 | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_div2 | 50 | 20.0 | synchronous-related | yes | divider out |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode == 0
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {pgen}" not in sgdc


def test_multi_domain_abstract_port_grouping(tmp_path):
    # driver-domain association: each data port groups under its OWN Clock Domain.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| clk2 | input | 1 | clk2 | clk | - | clock | - | - |\n"
        "| a | input | 8 | clk | cfg | APB3 | data | - | - |\n"
        "| b | input | 8 | clk2 | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk2 | 50 | 20.0 | async | no | second clock |\n",
    )
    _run(_wd(tmp_path, design))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {a} -clock clk" in sgdc
    assert "abstract_port -ports {b} -clock clk2" in sgdc


def test_input_only_module(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    summary = json.loads(_run(_wd(tmp_path, design)).stdout)
    assert summary["data_ports"] == 1
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_input_delay" in sdc and "set_output_delay" not in sdc


def test_output_only_module(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| dout | output | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    _run(_wd(tmp_path, design))
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_output_delay" in sdc and "set_input_delay" not in sdc


def test_no_data_port_module(tmp_path):
    # clock + reset only, no data ports → valid output, no false requirement.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst_n | input | 1 | clk | reset | - | reset | 0 | async |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    summary = json.loads(_run(_wd(tmp_path, design)).stdout)
    assert summary["data_ports"] == 0 and summary["resets"] == 1
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_input_delay" not in sdc and "set_output_delay" not in sdc


def test_short_named_data_port_on_generated_clock_deferred(tmp_path):
    # The generated-clock deferral applies regardless of signal-name length: a short
    # name 'd' on a generated clock is skipped (deferred to RTL), not fail-louded.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| d | input | 8 | clk_div2 | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_div2 | 50 | 20.0 | synchronous-related | yes | divider out |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode == 0
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {d}" not in sgdc


# ── finalize / build_result tests (Task 2) ─────────────────────────────────
_CLEAR_REVIEW = {
    "schema_version": 1,
    "stage": "specification",
    "module": "m",
    "reviewed_children": ["mac"],
    "verdict": "ok",
    "has_critical": False,
    "findings": [],
}


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


def test_build_result_pass_lean_shape(tmp_path):
    wd = _spec_workdir(tmp_path)
    assert (
        dc.build_result(wd, module="tpu_top", ppa_targets=[], waived=[], status="pass")
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


def test_build_result_passes_ppa_targets_through(tmp_path):
    wd = _spec_workdir(tmp_path)
    targets = [
        {"dim": "area_um2", "target": 70000.0},
        {"dim": "power_mw", "target": 12.5},
    ]
    dc.build_result(wd, module="tpu_top", ppa_targets=targets, waived=[], status="pass")
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert (
        ss["ppa_targets"] == targets
    )  # verbatim — orchestrate._ppa_targets reads this


def test_build_result_reject_status_writes_fail(tmp_path):
    # the human REJECTED at the Step-8 gate -> --status fail, gate still clear.
    wd = _spec_workdir(tmp_path)
    assert (
        dc.build_result(wd, module="tpu_top", ppa_targets=[], waived=[], status="fail")
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail" and env["stage_specific"]["fail_reason"]


# ── artifacts[] enumeration tests (Task 3) ─────────────────────────────────
def test_enumerate_artifacts_present_only_with_kinds(tmp_path):
    wd = _spec_workdir(tmp_path)
    dc.derive_constraints(
        wd
    )  # generate constraints/tpu_top.{sdc,sgdc} so they are present
    (wd / "fifo.md").write_text("# child\n")
    m = json.loads((wd / "manifest.json").read_text())
    m["children"].append({"name": "fifo", "doc": "fifo.md", "rtl_modules": ["fifo"]})
    (wd / "manifest.json").write_text(json.dumps(m))
    arts = dc.enumerate_artifacts(wd, top="tpu_top")
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
import shutil  # noqa: E402

from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"
_FIX = Path(__file__).resolve().parent / "fixtures" / "specification-tpu_top"


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


def test_golden_lean_against_real_tpu_top(tmp_path):
    wd = tmp_path / "specification"
    shutil.copytree(_FIX, wd)
    targets = [{"dim": "area_um2", "target": 70000.0}]
    # γ-floor: agent relays the human-gate outcome (approve, no waivers, PPA from D6).
    assert (
        dc.build_result(
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
    }
    assert "brainstorm.md" not in paths and "result.json" not in paths
    assert "notes" not in ss
    assert env["produced_at"].endswith("Z")
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
        dc.build_result(
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
    dc.build_result(wd, module="tpu_top", ppa_targets=[], waived=[], status="pass")
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert "approve precondition unmet" in env["stage_specific"]["fail_reason"]
