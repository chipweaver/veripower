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
    "stage": "specification",
    "module": "m",
    "reviewed_children": ["mac"],
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
    """A workdir derive_constraints() can run over (valid clocks.json + top-io.json) plus
    the finalize inputs (manifest/coverage/per-child md/spec-review)."""
    wd = tmp_path
    (wd / "design.md").write_text("# tpu_top Design\n\nNarrative only.\n")
    (wd / "top-io.json").write_text(
        json.dumps(
            [
                {
                    "name": "i_clk",
                    "direction": "input",
                    "width": 1,
                    "clock_domain": "i_clk",
                    "interface_group": "clk",
                    "role": "clock",
                }
            ]
        )
    )
    (wd / "clocks.json").write_text(
        json.dumps(
            [
                {
                    "name": "i_clk",
                    "freq_mhz": 100,
                    "period_ns": 10.0,
                    "relationship": "primary",
                    "role": "primary clock",
                }
            ]
        )
    )
    (wd / "manifest.json").write_text(
        json.dumps(
            {
                "module": "tpu_top",
                "children": [{"name": "mac", "doc": "mac.md", "rtl_modules": ["mac"]}],
            }
        )
    )
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
    assert (env["stage"], env["module"]) == (
        "specification",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["top_module"] == "tpu_top"
    assert ss["spec_gate"] == {
        "gate": "clear",
        "flagged": [],
        "must_ack": [],
        "waived": [],
    }
    assert (
        "ppa_targets" not in ss
    )  # PPA lives in the ppa.json sidecar, not the envelope
    assert "notes" not in ss and "fail_reason" not in ss  # lean shape
    assert json.loads((wd / "ppa.json").read_text()) == []  # sidecar written on pass
    assert {"path": "ppa.json"} in env["artifacts"]


def test_build_result_override_writes_ppa_sidecar(tmp_path):
    wd = _spec_workdir(tmp_path)
    targets = [
        {"dim": "area_um2", "target": 70000.0},
        {"dim": "power_mw", "target": 12.5},
    ]
    result.build_result(
        wd, module="tpu_top", ppa_targets=targets, waived=[], status="pass"
    )
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert "ppa_targets" not in ss  # the sidecar is the SSoT, not the envelope
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
def test_enumerate_artifacts_present_only(tmp_path):
    wd = _spec_workdir(tmp_path)
    constraints.derive_constraints(
        wd
    )  # generate constraints/tpu_top.{sdc,sgdc} so they are present
    (wd / "fifo.md").write_text("# child\n")
    m = json.loads((wd / "manifest.json").read_text())
    m["children"].append({"name": "fifo", "doc": "fifo.md", "rtl_modules": ["fifo"]})
    (wd / "manifest.json").write_text(json.dumps(m))
    arts = result.enumerate_artifacts(wd, top="tpu_top")
    paths = {a["path"] for a in arts}
    assert {
        "design.md",
        "manifest.json",
        "spec-review.json",
        "mac.md",
        "fifo.md",
        "constraints/tpu_top.sdc",
        "constraints/tpu_top.sgdc",
        "clocks.json",
    } <= paths
    assert all(set(a) == {"path"} for a in arts)  # the path IS the identity
    assert "brainstorm.md" not in paths and "result.json" not in paths
    assert all((wd / p).is_file() for p in paths)  # present-only


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
    assert (
        "ppa_targets" not in ss
    )  # PPA lives in the ppa.json sidecar, not the envelope
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
        "spec-review.json",
        "mac.md",
        "systolic_reg.md",
        "fifo.md",
        "tpu_top.md",
        "constraints/tpu_top.sdc",
        "constraints/tpu_top.sgdc",
        "ppa.json",
        "clocks.json",
        "features.json",
        "timing-scenarios.json",
        "top-io.json",
        "interconnects.json",
        "check-hints/mac.json",
        "check-hints/systolic_reg.json",
        "check-hints/fifo.json",
        "check-hints/tpu_top.json",
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
                "stage": "specification",
                "module": "tpu_top",
                "reviewed_children": ["mac"],
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
                "stage": "specification",
                "module": "tpu_top",
                "reviewed_children": ["mac"],
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


# ── waiver trust boundary: finalize rejects an unreasoned / malformed waiver (exit 2) ──
# The stderr message is asserted so the exit-2 is attributable to the waiver check, not to a
# downstream failure on the bare tmp_path (which would also exit 2, for a different reason).


def test_finalize_empty_reason_waiver_is_blocked(tmp_path, capsys):
    waived = json.dumps(
        [
            {
                "child": "mac",
                "lens": "faithfulness",
                "classification": "accepted-risk",
                "reason": "   ",
            }
        ]
    )
    rc = result.finalize(tmp_path, "tpu_top", status="pass", waived_json=waived)
    assert rc == 2
    assert "--waived" in capsys.readouterr().err


def test_finalize_bad_classification_waiver_is_blocked(tmp_path, capsys):
    waived = json.dumps(
        [
            {
                "child": "mac",
                "lens": "faithfulness",
                "classification": "meh",
                "reason": "x",
            }
        ]
    )
    rc = result.finalize(tmp_path, "tpu_top", status="pass", waived_json=waived)
    assert rc == 2
    assert "--waived" in capsys.readouterr().err


def test_finalize_missing_field_waiver_is_blocked(tmp_path, capsys):
    waived = json.dumps(
        [{"child": "mac", "classification": "false-positive", "reason": "x"}]
    )
    rc = result.finalize(tmp_path, "tpu_top", status="pass", waived_json=waived)
    assert rc == 2
    assert "--waived" in capsys.readouterr().err


def test_finalize_non_list_waiver_is_blocked(tmp_path, capsys):
    rc = result.finalize(tmp_path, "tpu_top", status="pass", waived_json='{"a": 1}')
    assert rc == 2
    assert "--waived" in capsys.readouterr().err


def test_finalize_valid_waiver_still_passes(tmp_path):
    # the check must not reject a well-formed human waiver: a valid one still clears the gate.
    wd = tmp_path / "specification"
    shutil.copytree(_FIX, wd)
    (wd / "spec-review.json").write_text(
        json.dumps(
            {
                "stage": "specification",
                "module": "tpu_top",
                "reviewed_children": ["mac"],
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
    waived = json.dumps(
        [
            {
                "child": "mac",
                "lens": "faithfulness",
                "location": "§1.3",
                "classification": "accepted-risk",
                "reason": "out of scope this tapeout",
            }
        ]
    )
    rc = result.finalize(
        wd, "tpu_top", status="pass", ppa_targets_json="[]", waived_json=waived
    )
    assert rc == 0
    assert json.loads((wd / "result.json").read_text())["status"] == "pass"


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


# ── ppa.json disk-read path (wave-1 product; --ppa-targets is an override) ──


def test_pass_reads_ppa_from_disk_when_no_override(tmp_path):
    wd = _spec_workdir(tmp_path)
    targets = [{"dim": "area_um2", "target": 70000.0}]
    (wd / "ppa.json").write_text(json.dumps(targets))
    assert (
        result.build_result(
            wd, module="tpu_top", ppa_targets=None, waived=[], status="pass"
        )
        == 0
    )
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert "ppa_targets" not in ss
    # the wave-1 disk copy IS the source — untouched, not rewritten
    assert json.loads((wd / "ppa.json").read_text()) == targets


def test_forgotten_override_no_longer_wipes_ppa_json(tmp_path):
    # regression: finalize WITHOUT --ppa-targets used to default to "[]" and
    # unconditionally rewrite ppa.json — silently disarming the downstream PPA gates.
    wd = _spec_workdir(tmp_path)
    targets = [{"dim": "power_mw", "target": 12.5}]
    (wd / "ppa.json").write_text(json.dumps(targets))
    MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--module",
            "tpu_top",
            "--status",
            "pass",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert json.loads((wd / "ppa.json").read_text()) == targets  # NOT wiped
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert "ppa_targets" not in ss


def test_pass_missing_ppa_json_is_blocked(tmp_path):
    wd = _spec_workdir(tmp_path)  # no ppa.json on disk
    rc = result.finalize(wd, "tpu_top", status="pass", waived_json="[]")
    assert rc == 2  # BLOCKED: wave-1 must emit ppa.json (or caller overrides)
    assert not (wd / "result.json").exists()


def test_pass_invalid_disk_ppa_is_blocked(tmp_path):
    wd = _spec_workdir(tmp_path)
    (wd / "ppa.json").write_text(json.dumps([{"dim": "bogus", "target": 1}]))
    assert result.finalize(wd, "tpu_top", status="pass", waived_json="[]") == 2


def test_invalid_override_is_blocked(tmp_path):
    wd = _spec_workdir(tmp_path)
    rc = result.finalize(
        wd,
        "tpu_top",
        status="pass",
        ppa_targets_json='[{"dim": "bogus", "target": 1}]',
        waived_json="[]",
    )
    assert rc == 2


# ── early-fail entry (--fail-reason): routable fail, full artifact carry ──


def test_early_fail_writes_reason_and_carries_artifacts(tmp_path):
    # a seeded rework workdir that fails early (e.g. unreadable trigger) must still
    # promote the FULL prior product set — an under-enumerated artifacts[] on a
    # promoted fail would GC canonical down to a hollow view (W4).
    wd = _spec_workdir(tmp_path)
    constraints.derive_constraints(
        wd
    )  # constraints present, as a seeded workdir would have
    (wd / "ppa.json").write_text("[]")
    assert (
        result.build_result(
            wd,
            module="tpu_top",
            ppa_targets=None,
            waived=[],
            status="fail",
            fail_reason="failing_result not readable: /x/result.json",
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    ss = env["stage_specific"]
    assert ss["fail_reason"] == "failing_result not readable: /x/result.json"
    assert ss["top_module"] == "tpu_top"  # from manifest.module, no derivation run
    paths = {a["path"] for a in env["artifacts"]}
    assert {
        "design.md",
        "manifest.json",
        "spec-review.json",
        "mac.md",
        "ppa.json",
        "constraints/tpu_top.sdc",
        "constraints/tpu_top.sgdc",
    } <= paths  # nothing dropped
    _validate_envelope(env)


def test_early_fail_without_review_record_omits_spec_gate(tmp_path):
    wd = _spec_workdir(tmp_path)
    (wd / "spec-review.json").unlink()  # early fail can precede the Step-7 wave
    assert (
        result.build_result(
            wd,
            module="tpu_top",
            ppa_targets=None,
            waived=[],
            status="fail",
            fail_reason="manifest child missing rtl_modules",
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert "spec_gate" not in env["stage_specific"]
    _validate_envelope(env)


def test_reject_default_reason_unchanged(tmp_path):
    # the human-reject path (no --fail-reason) keeps its established wording
    wd = _spec_workdir(tmp_path)
    result.build_result(wd, module="tpu_top", ppa_targets=[], waived=[], status="fail")
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "design.md gate rejected at human review"
    assert ss["spec_gate"]["gate"] == "clear"  # review record present -> still graded


# ── adversarial-review follow-ups: fail-path edges ──────────────────────────


def test_fail_without_manifest_is_blocked(tmp_path):
    # first-run wave-1 BLOCKED before manifest.json exists: finalize must exit 2
    # (fail-closed — a blocked run never promotes, so canonical cannot be GC'd
    # against a hollow view). Documented in the Fan-out carve-out edge note.
    rc = result.finalize(
        tmp_path, "tpu_top", status="fail", fail_reason="wave-1 BLOCKED: x"
    )
    assert rc == 2
    assert not (tmp_path / "result.json").exists()


def test_pass_ignores_fail_reason(tmp_path):
    wd = _spec_workdir(tmp_path)
    (wd / "ppa.json").write_text("[]")
    rc = result.finalize(
        wd, "tpu_top", status="pass", waived_json="[]", fail_reason="should be ignored"
    )
    assert rc == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert "fail_reason" not in env["stage_specific"]


def test_fail_path_merges_waived_into_spec_gate(tmp_path):
    wd = _spec_workdir(tmp_path)
    waived = [
        {
            "child": "mac",
            "lens": "faithfulness",
            "location": "§1.3",
            "classification": "accepted-risk",
            "reason": "human-authored",
        }
    ]
    assert (
        result.build_result(
            wd,
            module="tpu_top",
            ppa_targets=None,
            waived=waived,
            status="fail",
            fail_reason="requirements need revision: D2",
        )
        == 0
    )
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["spec_gate"]["waived"] == waived  # review record present -> merged


# ── code-review round: B-group fixes ─────────────────────────────────────────


def test_nan_ppa_is_blocked_on_both_paths(tmp_path):
    # Python's json.loads accepts the NaN token; the shape check must reject it
    # before it corrupts the ppa.json SSoT for strict downstream parsers.
    wd = _spec_workdir(tmp_path)
    rc = result.finalize(
        wd,
        "tpu_top",
        status="pass",
        ppa_targets_json='[{"dim": "power_mw", "target": NaN}]',
        waived_json="[]",
    )
    assert rc == 2
    (wd / "ppa.json").write_text('[{"dim": "power_mw", "target": NaN}]')
    assert result.finalize(wd, "tpu_top", status="pass", waived_json="[]") == 2


def test_corrupt_review_on_fail_is_blocked(tmp_path):
    # only an ABSENT spec-review.json is the legitimate early-fail case; a
    # present-but-corrupt record must surface (exit 2), never be silently dropped
    # from the promoted fail envelope.
    wd = _spec_workdir(tmp_path)
    (wd / "spec-review.json").write_text("{truncated")
    rc = result.finalize(
        wd, "tpu_top", status="fail", fail_reason="requirements need revision: D2"
    )
    assert rc == 2
    assert not (wd / "result.json").exists()


def test_precondition_downgrade_not_preempted_by_missing_ppa(tmp_path):
    # double fault: tripped review with no waiver AND no ppa.json — the documented
    # downgrade-to-fail must win; a ppa fault must not turn it into a no-write BLOCKED.
    wd = tmp_path / "specification"
    shutil.copytree(_FIX, wd)
    (wd / "spec-review.json").write_text(
        json.dumps(
            {
                "stage": "specification",
                "module": "tpu_top",
                "reviewed_children": ["mac"],
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
    assert not (wd / "ppa.json").exists()
    rc = result.finalize(wd, "tpu_top", status="pass", waived_json="[]")
    assert rc == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert "approve precondition unmet" in env["stage_specific"]["fail_reason"]


def test_derivation_failure_on_pass_is_blocked_exit2(tmp_path):
    # derive_constraints fail-louds via sys.exit (SystemExit, a BaseException);
    # finalize must keep its documented 0/2 contract instead of leaking exit 1.
    wd = _spec_workdir(tmp_path)
    (wd / "ppa.json").write_text("[]")
    # a non-numeric period now fails at clocks.json schema validation, not at a float()
    # of a table cell — the defect is caught by `type: number` before any rendering.
    (wd / "clocks.json").write_text(
        json.dumps(
            [
                {
                    "name": "i_clk",
                    "freq_mhz": 100,
                    "period_ns": "banana",
                    "relationship": "primary",
                }
            ]
        )
    )
    assert result.finalize(wd, "tpu_top", status="pass", waived_json="[]") == 2


def test_empty_fail_reason_is_blocked(tmp_path):
    # an empty --fail-reason must never be silently replaced by the human-reject
    # wording (that would fabricate a human-gate record for a run that had none).
    wd = _spec_workdir(tmp_path)
    rc = result.finalize(wd, "tpu_top", status="fail", fail_reason="   ")
    assert rc == 2
    assert not (wd / "result.json").exists()


def test_pass_non_string_scenario_id_is_blocked(tmp_path):
    # power-analysis matches a target to a scenario by string equality, so a non-string
    # scenario_id matches nothing and that target is silently never enforced.
    # ppa.schema.json already types the field; the hand-written check did not.
    wd = _spec_workdir(tmp_path)
    (wd / "ppa.json").write_text(
        json.dumps([{"dim": "power_mw", "target": 1, "scenario_id": 5}])
    )
    assert result.finalize(wd, "tpu_top", status="pass", waived_json="[]") == 2


def test_pass_non_finite_ppa_target_is_blocked(tmp_path):
    # Regression guard, green before and after the schema swap: NaN survives json.loads and
    # satisfies the schema's `type: number`, yet it makes power-analysis' `actual > target`
    # false for every input, disarming that gate. The explicit finite check must survive.
    wd = _spec_workdir(tmp_path)
    (wd / "ppa.json").write_text('[{"dim": "power_mw", "target": NaN}]')
    assert result.finalize(wd, "tpu_top", status="pass", waived_json="[]") == 2


def test_unreadable_ppa_schema_blocks_instead_of_waving_targets_through(
    tmp_path, monkeypatch
):
    # _validate_ppa is the only place ppa.json is ever validated, so a schema it cannot
    # read must fail closed.
    monkeypatch.setattr(result, "_PPA_SCHEMA", tmp_path / "absent.json")
    assert result._validate_ppa([{"dim": "power_mw", "target": 1}]) is not None
