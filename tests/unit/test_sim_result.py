# tests/unit/test_sim_result.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"
DEFAULTS = ROOT / "skills/simulation/defaults.yaml"

SCAFFOLD = {
    "module": "m",
    "top": "m_top",
    "agents": [{"name": "drv", "mode": "active"}, {"name": "obs", "mode": "passive"}],
    "sequences": [{"name": "smoke", "agent": "drv"}],
    "tests": [{"name": "t_smoke", "seqs": ["smoke"]}],
}
COV_PASS = {"aggregate": {"line": 92.0, "cond": 70.0, "fsm": 80.0, "toggle": 85.0}}


def _final_workdir(tmp_path):
    wd = tmp_path
    (wd / "tb/uvm/seq").mkdir(parents=True)
    (wd / "tb/uvm/agent").mkdir(parents=True)
    (wd / "tb/uvm/seq/m_smoke_seq.sv").write_text("class m_smoke_seq; endclass\n")
    for f in (
        "m_drv_driver.sv",
        "m_drv_monitor.sv",
        "m_drv_agent.sv",
        "m_obs_monitor.sv",
        "m_obs_agent.sv",
    ):
        (wd / "tb/uvm/agent" / f).write_text("class x; endclass\n")
    doc = dict(SCAFFOLD)
    (wd / "sequences.json").write_text(json.dumps(doc.pop("sequences", [])))
    (wd / "tb-scaffold.json").write_text(json.dumps(doc))
    (wd / "structural-coverage.json").write_text(json.dumps(COV_PASS))
    (wd / "case-results.json").write_text(
        json.dumps({"total_tests": 3, "passed_tests": 3, "failed_tests": 0})
    )
    # the rendered sibling: written by write_summary, read by a human, parsed by nobody
    (wd / "coverage-summary.txt").write_text(
        "suite_summary\ntotal_tests: 3\npassed_tests: 3\nfailed_tests: 0\n"
    )
    _review(wd)
    return wd


def _review(wd, *findings):
    """The reviewer's own record, as it stands on disk when finalize runs: one heading per
    finding, and a blocking one says so."""
    body = "# conformance review — m\n\n" + "\n\n".join(findings)
    (wd / "conformance-review.md").write_text(body + "\n")


def _finalize(wd, *extra):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--module",
            "m",
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def _finalize_final(wd, *extra):
    return _finalize(
        wd,
        "--phase",
        "final",
        "--plan",
        str(wd),
        "--thresholds",
        str(DEFAULTS),
        "--conformance-review",
        str(wd / "conformance-review.md"),
        *extra,
    )


def test_final_pass_writes_result(tmp_path):
    wd = _final_workdir(tmp_path)
    proc = _finalize_final(wd)
    assert proc.returncode == 0, proc.stderr
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "simulation" and env["status"] == "pass"
    assert env["stage_specific"]["total_cases"] == 3
    assert "result.json" not in [a["path"] for a in env["artifacts"]]


def test_verify_handoff_promoted(tmp_path):
    # TB-freeze §7 decision A: verify-handoff.json is promoted to artifacts[] so the
    # freeze classifier can locate it via the canonical result's artifact list.
    wd = _final_workdir(tmp_path)
    (wd / "verify-handoff.json").write_text("{}\n")
    proc = _finalize_final(wd)
    assert proc.returncode == 0, proc.stderr
    paths = [
        a["path"] for a in json.loads((wd / "result.json").read_text())["artifacts"]
    ]
    assert "verify-handoff.json" in paths
    assert "conformance-review.md" in paths  # a sibling handoff IS also promoted


def test_final_pass_missing_case_results_is_blocked(tmp_path):
    # S4: a missing case-results.json on the pass path is a broken pipeline step;
    # finalize must fail loud (exit 2 BLOCKED), not write null counts. Deleting only the
    # rendered coverage-summary.txt would NOT block — nothing reads it.
    wd = _final_workdir(tmp_path)
    (wd / "case-results.json").unlink()
    proc = _finalize_final(wd)
    assert proc.returncode == 2, proc.stdout
    assert not (wd / "result.json").exists()


def test_conformance_phase_writes_the_routing_envelope(tmp_path):
    # The fail-out carries the phase and the reason; the findings themselves stay in the
    # promoted review beside it, which is what triage opens. Copying them into the envelope
    # would duplicate a structured sibling in the same directory.
    proc = _finalize(
        tmp_path,
        "--phase",
        "conformance",
        "--fail-reason",
        "TP-01: check cannot detect the fault its intent names",
    )
    assert proc.returncode == 0, proc.stderr
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert ss["failure_phase"] == "conformance" and "TP-01" in ss["fail_reason"]
    assert "conformance_findings" not in ss


def test_final_thin_fail_is_compile(tmp_path):
    wd = _final_workdir(tmp_path)
    (wd / "tb/uvm/agent/m_drv_driver.sv").write_text("// TODO(driver)\n")  # residue
    proc = _finalize_final(wd)
    assert proc.returncode == 0
    env = json.loads((wd / "result.json").read_text())
    assert (
        env["status"] == "fail" and env["stage_specific"]["failure_phase"] == "compile"
    )


def test_final_coverage_fail(tmp_path):
    wd = _final_workdir(tmp_path)
    (wd / "structural-coverage.json").write_text(
        json.dumps(
            {"aggregate": {"line": 10.0, "cond": 70.0, "fsm": 80.0, "toggle": 85.0}}
        )
    )
    proc = _finalize_final(wd)
    assert (
        proc.returncode == 0
    )  # a coverage fail still writes result.json (exit 0, not BLOCKED)
    env = json.loads((wd / "result.json").read_text())
    assert (
        env["status"] == "fail" and env["stage_specific"]["failure_phase"] == "coverage"
    )
    assert env["stage_specific"]["dims"]["line"]["pass"] is False


def test_final_conformance_trip_is_fail_not_pass(tmp_path):
    # The one gate whose verdict finalize is handed rather than deriving alone. SKILL.md tells
    # the main thread it may not override a trip; until finalize itself refuses, that sentence
    # is the whole enforcement, and the main thread is the party it constrains.
    wd = _final_workdir(tmp_path)
    _review(
        wd,
        "## TP-01  tb/uvm/checker/m_sb.sv:10  BLOCKING\n"
        "mismatch logged as uvm_info; the counter never moves",
    )
    proc = _finalize_final(wd)
    assert proc.returncode == 0, proc.stderr
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["failure_phase"] == "conformance"
    assert "TP-01" in ss["fail_reason"]


def test_final_non_blocking_finding_does_not_trip(tmp_path):
    # A reported-but-not-blocking finding is the reviewer's own call; the backstop reads the
    # same call and must not turn the whole review into a second, stricter gate.
    wd = _final_workdir(tmp_path)
    _review(
        wd,
        "## TP-02  tb/uvm/checker/m_sb.sv:44\n"
        "handshake verified only end-to-end; no internal probe",
    )
    proc = _finalize_final(wd)
    assert proc.returncode == 0, proc.stderr
    assert json.loads((wd / "result.json").read_text())["status"] == "pass"


def test_final_compile_fail_carries_no_coverage_companions(tmp_path):
    # Companions follow the resolved failure_phase: a compile fail says nothing about
    # coverage, and the failure_phase table in SKILL.md lists none for it.
    wd = _final_workdir(tmp_path)
    (wd / "tb/uvm/agent/m_drv_driver.sv").write_text("// TODO(driver)\n")
    proc = _finalize_final(wd)
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert proc.returncode == 0
    assert "dims" not in ss and "coverage_extractable" not in ss


def test_early_exit_smoke(tmp_path):
    wd = tmp_path
    proc = _finalize(
        wd,
        "--phase",
        "smoke",
        "--failure-phase",
        "smoke",
        "--fail-reason",
        "case X failed",
    )
    assert proc.returncode == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail" and env["stage_specific"]["failure_phase"] == "smoke"
    assert env["stage_specific"]["fail_reason"] == "case X failed"


def test_final_requires_its_three_inputs_exit_2(tmp_path):
    # --conformance-review is one of them: defaulted to absent, the backstop above would read
    # an empty finding set and clear every review it was never given.
    wd = _final_workdir(tmp_path)
    for missing in ("--plan", "--thresholds", "--conformance-review"):
        flags = {
            "--plan": str(wd),
            "--thresholds": str(DEFAULTS),
            "--conformance-review": str(wd / "conformance-review.md"),
        }
        del flags[missing]
        args = [x for kv in flags.items() for x in kv]
        proc = _finalize(wd, "--phase", "final", *args)
        assert proc.returncode == 2, missing
        assert not (wd / "result.json").exists(), missing


def test_finalize_blocked_exit_2(tmp_path):
    # --phase final with a non-existent plan dir -> build_result raises -> exit 2 (BLOCKED)
    wd = _final_workdir(tmp_path)
    proc = _finalize(
        wd,
        "--phase",
        "final",
        "--plan",
        str(wd / "nope"),
        "--thresholds",
        str(DEFAULTS),
        "--conformance-review",
        str(wd / "conformance-review.md"),
    )
    assert proc.returncode == 2


# ── the one object array triage reads ──────────────────────────────────────────
_RESULT_SCHEMA = ROOT / "skills/simulation/references/result.schema.json"


def _ss_props():
    s = json.loads(_RESULT_SCHEMA.read_text())
    return s["allOf"][1]["properties"]["stage_specific"]["properties"]


def test_failing_cases_pins_what_triage_reads():
    # simulation-triage resolves logs/<test_id>.log and anchors Step 1 on error_message; both
    # must be required, and the entry closed so a producer typo fails here rather than silently
    # giving triage nothing to read.
    item = _ss_props()["failing_cases"]["items"]
    assert sorted(item["required"]) == ["error_message", "test_id"]
    assert item["additionalProperties"] is False
    assert (
        "log_snippet" in item["properties"]
    )  # optional: triage falls back to the full log
