# tests/unit/test_validate_sim_exit.py
"""Tests for validate_sim_exit.py: thin-D1 + D5 + D6 one-pass exit gate."""

import importlib.util
import json
import subprocess
import sys as _sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/simulation/scripts/validate_sim_exit.py"
DEFAULTS = ROOT / "skills/simulation/defaults.yaml"

# Load the host as an in-process module so build_result / main(argv) are callable.
_spec = importlib.util.spec_from_file_location("validate_sim_exit", SCRIPT)
vse = importlib.util.module_from_spec(_spec)
_sys.modules["validate_sim_exit"] = vse
_spec.loader.exec_module(vse)

SCAFFOLD = {
    "module": "m",
    "top": "m_top",
    "agents": [{"name": "drv", "mode": "active"}, {"name": "obs", "mode": "passive"}],
    "sequences": [{"name": "smoke", "agent": "drv"}],
    "tests": [{"name": "t_smoke", "seqs": ["smoke"]}],
}
# Coverage above the Task-1 thresholds (line>=80 cond>=60 fsm>=50 toggle>=70).
COV_PASS = {
    "aggregate": {
        "line": 92.0,
        "cond": 70.0,
        "fsm": 80.0,
        "toggle": 85.0,
        "branch": 90.0,
        "score": 84.0,
    },
    "per_module": [],
}


def _workdir(tmp_path, scaffold=SCAFFOLD, cov=COV_PASS, todo=False, drop_seq=False):
    wd = tmp_path
    (wd / "tb/uvm/seq").mkdir(parents=True)
    (wd / "tb/uvm/agent").mkdir(parents=True)
    if not drop_seq:
        (wd / "tb/uvm/seq/m_smoke_seq.sv").write_text(
            "class m_smoke_seq; task body(); endtask endclass\n"
        )
    # Deploy the infra base class (post-Task-2b: reworded, NO "TODO") to prove the plain-TODO
    # regex does not false-positive on the always-present infra layer in a completed TB.
    (wd / "tb/uvm/seq/base_seq.sv").write_text(
        "class m_base_seq; task body();\n"
        '  `uvm_info(get_type_name(), "NOTE: base body is a no-op; override in subclass.", UVM_LOW)\n'
        "endtask endclass\n"
    )
    body = "// TODO(driver): fill\n" if todo else "class m_drv_driver; endclass\n"
    (wd / "tb/uvm/agent/m_drv_driver.sv").write_text(body)
    (wd / "tb/uvm/agent/m_drv_monitor.sv").write_text("class m_drv_monitor; endclass\n")
    (wd / "tb/uvm/agent/m_drv_agent.sv").write_text("class m_drv_agent; endclass\n")
    (wd / "tb/uvm/agent/m_obs_monitor.sv").write_text("class m_obs_monitor; endclass\n")
    (wd / "tb/uvm/agent/m_obs_agent.sv").write_text("class m_obs_agent; endclass\n")
    (wd / "scaffold-specification.json").write_text(json.dumps(scaffold))
    if cov is not None:
        (wd / "structural-coverage.json").write_text(json.dumps(cov))
    return wd


def _run(wd, check=True):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--workdir",
            str(wd),
            "--scaffold",
            str(wd / "scaffold-specification.json"),
            "--thresholds",
            str(DEFAULTS),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def test_all_pass(tmp_path):
    proc = _run(_workdir(tmp_path))
    assert proc.returncode == 0 and "OK" in proc.stdout


def test_d6_below_threshold_fails(tmp_path):
    cov = {
        "aggregate": {
            "line": 45.0,
            "cond": 20.0,
            "fsm": 7.0,
            "toggle": 27.0,
            "branch": 33.0,
            "score": 26.0,
        },
        "per_module": [],
    }
    proc = _run(_workdir(tmp_path, cov=cov), check=False)
    assert proc.returncode != 0 and "fsm" in proc.stderr and "line" in proc.stderr
    # the fail path still emits the agent-consumed verdict JSON on stdout (last line)
    verdict = json.loads(proc.stdout.strip().splitlines()[-1])
    assert (
        verdict["coverage_extractable"] is True
    )  # coverage IS extractable; gate failed on value
    assert verdict["dims"]["fsm"]["pass"] is False


def test_d6_skips_absent_dim(tmp_path):
    # datapath DUT: fsm is None (no FSM) -> skip, do not fail on it.
    cov = {
        "aggregate": {
            "line": 92.0,
            "cond": 70.0,
            "fsm": None,
            "toggle": 85.0,
            "branch": 90.0,
            "score": 84.0,
        },
        "per_module": [],
    }
    assert _run(_workdir(tmp_path, cov=cov)).returncode == 0


def test_d5_missing_coverage_fails(tmp_path):
    proc = _run(_workdir(tmp_path, cov=None), check=False)
    assert proc.returncode != 0 and "coverage" in proc.stderr.lower()


def test_d1_todo_residue_fails(tmp_path):
    proc = _run(_workdir(tmp_path, todo=True), check=False)
    assert proc.returncode != 0 and "TODO" in proc.stderr


def test_d1_missing_seq_file_fails(tmp_path):
    proc = _run(_workdir(tmp_path, drop_seq=True), check=False)
    assert proc.returncode != 0 and "m_smoke_seq" in proc.stderr


def test_d1_unreworded_base_seq_todo_fails(tmp_path):
    # Guards Task 2b: an infra base_seq still carrying the old "TODO:" string must fail the
    # plain-TODO gate -- proves the template cleanup is load-bearing, not cosmetic.
    wd = _workdir(tmp_path)
    (wd / "tb/uvm/seq/base_seq.sv").write_text(
        "class m_base_seq; task body();\n"
        '  `uvm_info(get_type_name(), "TODO: drive spec-derived stimulus here.", UVM_LOW)\n'
        "endtask endclass\n"
    )
    proc = _run(wd, check=False)
    assert proc.returncode != 0 and "base_seq" in proc.stderr


def test_d1_todo_in_svh_fails(tmp_path):
    # derive_scaffold emits tb/uvm/test/generated_tests.svh; an unfilled no-seq test leaves
    # "// TODO: Start sequences here." there. The .svh must be scanned, not just .sv.
    wd = _workdir(tmp_path)
    (wd / "tb/uvm/test").mkdir(parents=True)
    (wd / "tb/uvm/test/generated_tests.svh").write_text(
        "// TODO: Start sequences here.\n"
    )
    proc = _run(wd, check=False)
    assert proc.returncode != 0 and "generated_tests.svh" in proc.stderr


def test_verdict_json_on_stdout(tmp_path):
    proc = _run(_workdir(tmp_path))
    # last stdout line is a JSON verdict the agent copies into result.json stage_specific
    verdict = json.loads(proc.stdout.strip().splitlines()[-1])
    assert verdict["coverage_extractable"] is True
    assert verdict["dims"]["fsm"]["pass"] is True


def _run_thin(wd, check=True):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--workdir",
            str(wd),
            "--scaffold",
            str(wd / "scaffold-specification.json"),
            "--thin-only",
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def test_thin_only_clean_passes_without_thresholds(tmp_path):
    """--thin-only gates on materialization only; --thresholds is NOT required and
    coverage is not consulted (no structural-coverage.json present here)."""
    proc = _run_thin(_workdir(tmp_path, cov=None))
    assert proc.returncode == 0 and "OK" in proc.stdout


def test_thin_only_todo_fails(tmp_path):
    proc = _run_thin(_workdir(tmp_path, cov=None, todo=True), check=False)
    assert proc.returncode != 0 and "TODO" in proc.stderr


def test_thin_only_missing_file_fails(tmp_path):
    proc = _run_thin(_workdir(tmp_path, cov=None, drop_seq=True), check=False)
    assert proc.returncode != 0 and "m_smoke_seq" in proc.stderr


def test_thin_only_verdict_is_trimmed(tmp_path):
    """--thin-only verdict carries only {unmaterialized, todo_residue} -- no coverage keys."""
    proc = _run_thin(_workdir(tmp_path, cov=None))
    verdict = json.loads(proc.stdout.strip().splitlines()[-1])
    assert set(verdict.keys()) == {"unmaterialized", "todo_residue"}


# ── finalize: build_result + --phase (Tasks 1-5) ─────────────────────────────


def _conformance(tmp_path, findings):
    p = tmp_path / "conformance-review.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": "simulation",
                "module": "m",
                "reviewed_testpoints": [f["tp_id"] for f in findings],
                "verdict": (
                    "concerns"
                    if any(f["category"] != "unavailable" for f in findings)
                    else "ok"
                ),
                "has_critical": any(f["severity"] == "critical" for f in findings),
                "findings": findings,
            }
        )
    )
    return p


ADV = [
    {
        "tp_id": "TP-X",
        "severity": "minor",
        "category": "unverifiable-arch",
        "location": "tb/x:1",
        "summary": "no drive path; reset-release IS checked",
    }
]


def test_finalize_final_clean_pass_lean_shape(tmp_path):
    wd = _workdir(tmp_path)  # materialized + covered, no TODO
    (wd / "coverage-summary.txt").write_text(
        "suite_summary\ntotal_tests: 7\npassed_tests: 7\nfailed_tests: 0\n"
    )
    rev = _conformance(tmp_path, ADV)
    verify = tmp_path / "verify.json"
    verify.write_text('{"stimulus_iterations": 1}')
    rc = vse.build_result(
        wd,
        module="m",
        phase="final",
        scaffold=wd / "scaffold-specification.json",
        thresholds=DEFAULTS,
        conformance_review=rev,
        verify_verdict=verify,
        fail_reason=None,
    )
    assert rc == 0
    env = json.loads((wd / "result.json").read_text())
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "simulation",
        "m",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert (ss["total_cases"], ss["passed"], ss["failed"]) == (7, 7, 0)
    assert ss["stimulus_iterations"] == 1
    assert ss["coverage_summary"] == {
        "line": 92.0,
        "cond": 70.0,
        "fsm": 80.0,
        "toggle": 85.0,
    }
    assert ss["conformance_gate"] == "clear"
    adv = ss["conformance_advisory"][0]
    assert adv == {
        "tp_id": "TP-X",
        "category": "unverifiable-arch",
        "severity": "minor",
        "note": "no drive path; reset-release IS checked",
    }  # note = summary verbatim
    for k in ("notes", "note", "failure_phase", "fail_reason", "compile_rounds"):
        assert k not in ss  # lean: no run-narration, no fail fields on pass


def test_finalize_final_coverage_fail(tmp_path):
    wd = _workdir(tmp_path)
    (wd / "structural-coverage.json").unlink()  # coverage_gate D5 trips
    rc = vse.build_result(
        wd,
        module="m",
        phase="final",
        scaffold=wd / "scaffold-specification.json",
        thresholds=DEFAULTS,
        conformance_review=None,
        verify_verdict=None,
        fail_reason=None,
    )
    assert rc == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["failure_phase"] == "coverage" and ss["fail_reason"]
    assert ss["coverage_extractable"] is False


def test_legacy_exit_check_cli_still_green(tmp_path):
    # the bare exit-check invocation (no subcommand) is byte-unchanged — back-compat guard
    proc = _run(_workdir(tmp_path))  # the existing _run helper, no "finalize"
    assert proc.returncode == 0 and "OK" in proc.stdout


# --- Task 2: pass-summary derivations ---------------------------------------


def test_read_case_counts_from_coverage_summary(tmp_path):
    (tmp_path / "coverage-summary.txt").write_text(
        "suite_summary\ntotal_tests: 7\npassed_tests: 7\nfailed_tests: 0\n"
        "manual_review_tests: 0\nnot_run_tests: 0\n"
    )
    assert vse.read_case_counts(tmp_path) == {"total": 7, "passed": 7, "failed": 0}


def test_read_coverage_summary_four_dims(tmp_path):
    (tmp_path / "structural-coverage.json").write_text(
        json.dumps(
            {
                "aggregate": {
                    "score": 93.33,
                    "line": 100.0,
                    "cond": 88.89,
                    "toggle": 84.42,
                    "fsm": None,
                    "branch": 100.0,
                }
            }
        )
    )
    assert vse.read_coverage_summary(tmp_path) == {
        "line": 100.0,
        "cond": 88.89,
        "fsm": None,
        "toggle": 84.42,
    }  # branch/score dropped


def test_conformance_gate_and_advisory(tmp_path):
    review = tmp_path / "conformance-review.json"
    review.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "tp_id": "TP-X",
                        "severity": "minor",
                        "category": "unverifiable-arch",
                        "location": "tb/x:1",
                        "summary": "no drive path; reset-release IS checked",
                    },
                    {
                        "tp_id": "TP-Y",
                        "severity": "critical",
                        "category": "missing",
                        "location": "tb/y:2",
                        "summary": "check absent",
                    },
                ]
            }
        )
    )
    assert vse.conformance_gate_label(review) == "trip"  # TP-Y gates (via compute_gate)
    adv = vse.conformance_advisory(review)
    assert [a["tp_id"] for a in adv] == ["TP-X"]  # only the advisory finding
    assert adv[0] == {
        "tp_id": "TP-X",
        "category": "unverifiable-arch",
        "severity": "minor",
        "note": "no drive path; reset-release IS checked",
    }  # note = summary verbatim


# --- Task 3: artifacts[] enumeration ----------------------------------------


def test_enumerate_artifacts_present_only_no_self(tmp_path):
    for rel in [
        "Makefile",
        "env.sh",
        "filelist.f",
        "rtl_filelist.f",
        "tests/testlist.json",
        "regression-log.txt",
        "verify-handoff.json",
        "conformance-review.json",
        "structural-coverage.json",
        "coverage-summary.txt",
        "case-results-summary.md",
    ]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    for d in ["tb/uvm", "scripts", "logs"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in vse.enumerate_artifacts(tmp_path)]
    assert "tb/uvm" in paths and "scripts" in paths and "logs" in paths
    assert "regression-log.txt" in paths and "conformance-review.json" in paths
    assert "result.json" not in paths
    assert all((tmp_path / p).exists() for p in paths)  # present files/dirs only


# --- Task 4: the early-exit write-points (every --phase closed) -------------


def _finalize_phase(wd, phase, **kw):
    argv = [
        "validate_sim_exit.py",
        "finalize",
        "--workdir",
        str(wd),
        "--module",
        "m",
        "--phase",
        phase,
    ]
    for k, v in kw.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    return vse.main(argv)


def test_phase_prerequisite_writes_fail(tmp_path):
    assert (
        _finalize_phase(
            tmp_path,
            "prerequisite",
            fail_reason="external reference missing: rtl-design/result.json",
        )
        == 0
    )
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert ss["failure_phase"] == "prerequisite"
    assert ss["fail_reason"].startswith("external reference missing")
    for k in ("total_cases", "conformance_gate"):
        assert k not in ss  # no pass-summary on an early-exit fail


def test_phase_env_blocked_carries_observed_failure_phase(tmp_path):
    # env-build BLOCKED with a Rule-A compile block -> failure_phase=compile + compile_rounds
    verify = tmp_path / "v.json"
    verify.write_text('{"compile_rounds": 2}')
    assert (
        _finalize_phase(
            tmp_path,
            "env-blocked",
            failure_phase="compile",
            fail_reason="Rule A budget exhausted",
            verify_verdict=verify,
        )
        == 0
    )
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert ss["failure_phase"] == "compile" and ss["compile_rounds"] == 2


def test_phase_smoke_carries_failing_cases(tmp_path):
    verify = tmp_path / "v.json"
    verify.write_text('{"failing_cases": [{"name": "t_smoke"}]}')
    assert (
        _finalize_phase(
            tmp_path,
            "smoke",
            failure_phase="smoke",
            fail_reason="a RESULT line is FAIL",
            verify_verdict=verify,
        )
        == 0
    )
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert ss["failure_phase"] == "smoke" and ss["failing_cases"] == [
        {"name": "t_smoke"}
    ]


def test_phase_conformance_carries_findings(tmp_path):
    rev = _conformance(
        tmp_path,
        [
            {
                "tp_id": "TP-Y",
                "severity": "critical",
                "category": "missing",
                "location": "tb/y:2",
                "summary": "check absent",
            }
        ],
    )
    assert (
        _finalize_phase(
            tmp_path,
            "conformance",
            fail_reason="TP-Y missing (critical)",
            conformance_review=rev,
        )
        == 0
    )
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert ss["failure_phase"] == "conformance"
    assert [f["tp_id"] for f in ss["conformance_findings"]] == ["TP-Y"]  # gating subset


def test_phase_regress_carries_failing_cases(tmp_path):
    # verify-wave route-out: make regress had a failing case -> failure_phase=regress
    verify = tmp_path / "v.json"
    verify.write_text('{"failing_cases": [{"name": "t_axi_burst"}]}')
    assert (
        _finalize_phase(
            tmp_path,
            "regress",
            failure_phase="regress",
            fail_reason="1 case failed in make regress",
            verify_verdict=verify,
        )
        == 0
    )
    env = json.loads((tmp_path / "result.json").read_text())
    ss = env["stage_specific"]
    assert (
        env["status"] == "fail"
    )  # verify route-out writes status=fail, skips --phase final
    assert ss["failure_phase"] == "regress" and ss["failing_cases"] == [
        {"name": "t_axi_burst"}
    ]
    for k in ("coverage_gaps", "total_cases"):
        assert k not in ss


def test_phase_regress_rule_b_coverage_carries_gaps(tmp_path):
    # the verify wave can ALSO route out on Rule-B coverage -> failure_phase=coverage (not regress)
    verify = tmp_path / "v.json"
    verify.write_text(
        '{"coverage_gaps": ["fifo.full_then_pop"], "gaps_not_in_testpoints": ["fifo.full_then_pop"]}'
    )
    assert (
        _finalize_phase(
            tmp_path,
            "regress",
            failure_phase="coverage",
            fail_reason="uncovered bins outside testpoints (Rule B)",
            verify_verdict=verify,
        )
        == 0
    )
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert ss["failure_phase"] == "coverage"
    assert ss["coverage_gaps"] == ["fifo.full_then_pop"]
    assert ss["gaps_not_in_testpoints"] == ["fifo.full_then_pop"]
    assert "failing_cases" not in ss


def test_phase_verify_blocked_maps_to_fail(tmp_path):
    # STATUS: BLOCKED is a harness-level signal -> status=fail, default failure_phase=regress
    assert (
        _finalize_phase(
            tmp_path,
            "verify-blocked",
            fail_reason="verify child BLOCKED: simulator license unavailable",
        )
        == 0
    )
    env = json.loads((tmp_path / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail" and ss["failure_phase"] == "regress"
    assert ss["fail_reason"].startswith("verify child BLOCKED")
    for k in ("failing_cases", "coverage_gaps", "total_cases"):
        assert k not in ss


# --- Task 5: golden test against the real tpu_top run -----------------------

import shutil  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "simulation-tpu_top"


def test_golden_clean_pass_against_real_tpu_top(tmp_path):
    wd = tmp_path / "simulation"
    shutil.copytree(FIX, wd)
    rc = vse.build_result(
        wd,
        module="tpu_top",
        phase="final",
        scaffold=wd / "scaffold-specification.json",
        thresholds=wd / "defaults.yaml",
        conformance_review=wd / "conformance-review.json",
        verify_verdict=wd / "verify-verdict.json",
        fail_reason=None,
    )
    assert rc == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "pass"
    assert (ss["total_cases"], ss["passed"], ss["failed"]) == (7, 7, 0)
    assert ss["stimulus_iterations"] == 1
    assert ss["coverage_summary"] == {
        "line": 100.0,
        "cond": 88.89,
        "fsm": None,
        "toggle": 84.42,
    }
    assert ss["conformance_gate"] == "clear"
    # advisory note copied VERBATIM from the source finding summary (NOT the old reworded note)
    src = {
        f["tp_id"]: f["summary"]
        for f in json.loads((wd / "conformance-review.json").read_text())["findings"]
    }
    for a in ss["conformance_advisory"]:
        assert a["note"] == src[a["tp_id"]]
    for k in ("notes", "note", "failure_phase", "fail_reason", "compile_rounds"):
        assert k not in ss  # lean: dropped fields absent
    paths = [a["path"] for a in env["artifacts"]]
    assert "tb/uvm" in paths and "conformance-review.json" in paths
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")


def test_golden_is_schema_valid(tmp_path):
    # Validate the golden result.json against the per-stage schema + envelope $ref,
    # via a self-contained Registry (NOT _validate_envelope, which is signoff-bound).
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    wd = tmp_path / "simulation"
    shutil.copytree(FIX, wd)
    vse.build_result(
        wd,
        module="tpu_top",
        phase="final",
        scaffold=wd / "scaffold-specification.json",
        thresholds=wd / "defaults.yaml",
        conformance_review=wd / "conformance-review.json",
        verify_verdict=wd / "verify-verdict.json",
        fail_reason=None,
    )
    env = json.loads((wd / "result.json").read_text())
    stage_schema = json.loads(
        (ROOT / "skills/simulation/references/result.schema.json").read_text()
    )
    envelope_schema = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    registry = Registry().with_resource(
        "https://veripower.local/schemas/envelope.schema.json",
        Resource.from_contents(envelope_schema),
    )
    validator = Draft202012Validator(stage_schema, registry=registry)
    errors = sorted(validator.iter_errors(env), key=lambda e: list(e.absolute_path))
    assert not errors, (
        "golden simulation result.json is not schema-valid: "
        + "; ".join(
            f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in errors
        )
    )
