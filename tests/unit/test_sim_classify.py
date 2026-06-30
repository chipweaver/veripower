"""sim classify-delta — trigger-agnostic first-run/freeze/rebuild verdict (+ P1-A conformance-real)."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "skills/simulation/scripts/sim/__main__.py"
sys.path.insert(0, str(REPO_ROOT / "skills/simulation/scripts"))
from sim import classify  # noqa: E402


def _plan(tmp_path, scaffold='{"module":"m"}', plan="# plan\n"):
    s = tmp_path / "scaffold-specification.json"
    p = tmp_path / "verification-plan.md"
    s.write_text(scaffold)
    p.write_text(plan)
    return s, p


def _baseline(
    tmp_path,
    *,
    status="pass",
    failure_phase=None,
    plan_digest="ABSENT",
    conformance="real",
):
    ss = {}
    if failure_phase is not None:
        ss["failure_phase"] = failure_phase
        ss["fail_reason"] = "x"
    if plan_digest != "ABSENT":
        ss["plan_digest"] = plan_digest
    rj = {
        "schema_version": 1,
        "stage": "simulation",
        "module": "m",
        "produced_at": "2026-06-30T00:00:00Z",
        "status": status,
        "artifacts": [],
        "stage_specific": ss,
    }
    (tmp_path / "result.json").write_text(json.dumps(rj))
    cr = (
        tmp_path / "conformance-review.json"
    )  # sibling read by _conformance_real (P1-A)
    if conformance == "real":
        cr.write_text(json.dumps({"verdict": "ok", "findings": []}))
    elif conformance == "unavailable":
        cr.write_text(
            json.dumps(
                {
                    "findings": [
                        {
                            "tp_id": "-",
                            "category": "unavailable",
                            "summary": "review failed",
                        }
                    ]
                }
            )
        )
    # conformance == "absent": write none
    return tmp_path / "result.json"


# ── in-process logic tests ──────────────────────────────────────────────────
def test_plan_digest_stable_and_separated(tmp_path):
    s, p = _plan(tmp_path)
    d = classify.plan_digest(s, p)
    assert d == classify.plan_digest(s, p)
    p.write_text("# plan v2\n")
    assert classify.plan_digest(s, p) != d


def test_first_run_when_no_canonical(tmp_path):
    s, p = _plan(tmp_path)
    assert (
        classify.classify_delta(tmp_path / "nope.json", s, p)["verdict"] == "first-run"
    )


def test_freeze_when_pass_and_digest_matches(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(tmp_path, status="pass", plan_digest=classify.plan_digest(s, p))
    assert classify.classify_delta(rj, s, p)["verdict"] == "freeze"


def test_rebuild_when_digest_differs(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(tmp_path, status="pass", plan_digest="deadbeef")
    assert classify.classify_delta(rj, s, p)["verdict"] == "rebuild"


def test_freeze_on_regress_fail_baseline(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(
        tmp_path,
        status="fail",
        failure_phase="regress",
        plan_digest=classify.plan_digest(s, p),
    )
    assert classify.classify_delta(rj, s, p)["verdict"] == "freeze"


def test_freeze_on_coverage_fail_baseline(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(
        tmp_path,
        status="fail",
        failure_phase="coverage",
        plan_digest=classify.plan_digest(s, p),
    )
    assert classify.classify_delta(rj, s, p)["verdict"] == "freeze"


def test_rebuild_on_compile_fail_baseline(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(
        tmp_path,
        status="fail",
        failure_phase="compile",
        plan_digest=classify.plan_digest(s, p),
    )
    assert classify.classify_delta(rj, s, p)["verdict"] == "rebuild"


def test_rebuild_on_smoke_fail_baseline(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(
        tmp_path,
        status="fail",
        failure_phase="smoke",
        plan_digest=classify.plan_digest(s, p),
    )
    assert classify.classify_delta(rj, s, p)["verdict"] == "rebuild"


def test_rebuild_on_prerequisite_fail_baseline(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(
        tmp_path,
        status="fail",
        failure_phase="prerequisite",
        plan_digest=classify.plan_digest(s, p),
    )
    assert classify.classify_delta(rj, s, p)["verdict"] == "rebuild"


def test_rebuild_when_legacy_no_plan_digest(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(tmp_path, status="pass")  # plan_digest absent
    assert classify.classify_delta(rj, s, p)["verdict"] == "rebuild"


def test_rebuild_when_conformance_unavailable(tmp_path):
    # P1-A: baseline whose conformance review never ran (unavailable stub) is NOT freeze-eligible.
    s, p = _plan(tmp_path)
    rj = _baseline(
        tmp_path,
        status="pass",
        plan_digest=classify.plan_digest(s, p),
        conformance="unavailable",
    )
    assert classify.classify_delta(rj, s, p)["verdict"] == "rebuild"


def test_rebuild_when_conformance_absent(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(
        tmp_path,
        status="pass",
        plan_digest=classify.plan_digest(s, p),
        conformance="absent",
    )
    assert classify.classify_delta(rj, s, p)["verdict"] == "rebuild"


# ── subprocess verb wiring ──────────────────────────────────────────────────
def test_verb_emits_verdict_json(tmp_path):
    s, p = _plan(tmp_path)
    rj = _baseline(tmp_path, status="pass", plan_digest=classify.plan_digest(s, p))
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "classify-delta",
            "--scaffold",
            str(s),
            "--plan",
            str(p),
            "--canonical-result",
            str(rj),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip())["verdict"] == "freeze"


def test_verb_first_run_without_canonical(tmp_path):
    s, p = _plan(tmp_path)
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "classify-delta",
            "--scaffold",
            str(s),
            "--plan",
            str(p),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and json.loads(r.stdout.strip())["verdict"] == "first-run"
