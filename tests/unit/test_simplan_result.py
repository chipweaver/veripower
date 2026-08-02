"""Tests for the simplan finalize verb — build_result + human-gate args + enumerate."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation-plan" / "scripts"))
from simplan import result as vs  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
SPEC_FIX = FIX / "specification-tpu_top"

# A post-materialize scaffold that really passes check-scaffold: finalize re-runs the gate
# in-process, so a synthetic shape that the gate would reject is not a usable fixture here.
GOOD = {
    "module": "m",
    "top": "m_top",
    "agents": [
        {
            "name": "drv",
            "mode": "active",
            "interface_groups": ["cfg"],
            "interface": {"signals": [{"name": "wdata", "width": 32}]},
            "transaction": {
                "fields": [
                    {"name": "wdata", "width": 32, "type": "logic", "rand": True}
                ]
            },
        },
        {
            "name": "obs",
            "mode": "passive",
            "interface_groups": ["stat"],
            "interface": {"signals": [{"name": "rdata", "width": 32}]},
            "transaction": {
                "fields": [
                    {"name": "rdata", "width": 32, "type": "logic", "rand": True}
                ]
            },
        },
    ],
    "sequences": [{"name": "smoke", "agent": "drv", "desc": "smoke"}],
    "tests": [
        {
            "name": "t_smoke",
            "feature": "F1",
            "test_id": "T1",
            "suites": ["smoke", "regress"],
            "feature_name": "Register write path",
            "seqs": ["smoke"],
        }
    ],
    "rm": {"name": "m_rm", "inports": ["drv"]},
    "scoreboard": {"name": "m_sb", "observer": "obs"},
    "primary_clock": {"dut_port_name": "clk", "period_ns": 10.0},
    "reset": {"dut_port_name": "rst_n"},
    "testpoints": [
        {
            "id": "TP-1",
            "intent": "drive a write and observe the read-back",
            "bins": ["a"],
            "covers": ["CHK-0"],
            "inlined_check_hints": [
                {"check_id": "CHK-0", "implementation_detail": "x"}
            ],
        }
    ],
    "power_scenarios": [
        {
            "id": "S1",
            "sequence_ref": "smoke",
            "corner_intent": "SS/125C",
        }
    ],
}


def _split(wd, scaffold):
    """The plan's machine half is three files on disk; the tests author one dict."""
    doc = dict(scaffold)
    for name, key in (
        ("sequences.json", "sequences"),
        ("power-scenarios.json", "power_scenarios"),
    ):
        (wd / name).write_text(json.dumps(doc.pop(key, [])))
    (wd / "tb-scaffold.json").write_text(json.dumps(doc))


def _spec(tmp_path, hints=("CHK-0",)):
    """A minimal specification workdir for the coverage layer finalize re-runs."""
    sd = tmp_path / "spec"
    (sd / "check-hints").mkdir(parents=True, exist_ok=True)
    (sd / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "c", "doc": "c.md"}]})
    )
    (sd / "check-hints" / "c.json").write_text(
        json.dumps([{"check_id": c} for c in hints])
    )
    return sd


def _finalize_workdir(tmp_path, *, scaffold=None, review=True):
    wd = tmp_path / "plan"
    wd.mkdir()
    _split(wd, scaffold or GOOD)
    (wd / "verification-plan.md").write_text(
        "# Plan\n## 3. Testpoints\nSee tb-scaffold.json testpoints[].\n"
    )
    if review:
        (wd / "plan-review").mkdir()
        (wd / "plan-review" / "review.md").write_text("# Review\n\nNo blockers.\n")
    return wd


def test_build_result_pass_lean_shape(tmp_path):
    wd = _finalize_workdir(tmp_path)
    spec = _spec(tmp_path)
    assert vs.build_result(wd, spec, status=None, revision=None) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "simulation-plan"
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    # Lean shape: nothing at all on a plain pass. The review is prose under plan-review/,
    # fingerprinted as the oracle; no verdict derived from it reaches the envelope.
    assert env["stage_specific"] == {}


def test_build_result_carries_revision(tmp_path):
    wd = _finalize_workdir(tmp_path)
    spec = _spec(tmp_path)
    rev = "rev 0.2 (rework r1): narrowed TP-1 bins"
    assert vs.build_result(wd, spec, status=None, revision=rev) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss == {
        "revision": rev
    }  # human-gate narration, not derivable from any artifact


def test_build_result_fail_on_user_reject(tmp_path):
    wd = _finalize_workdir(tmp_path)
    spec = _spec(tmp_path)
    assert vs.build_result(wd, spec, status="fail", revision=None) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"] == {"fail_reason": "user rejected plan"}


def test_pass_blocked_when_scaffold_edited_after_the_gate(tmp_path):
    # The invariant finalize exists to re-witness: Step 2 left check-scaffold clean, so a
    # failure here means an artifact changed afterwards — BLOCKED, not a routable fail.
    wd = _finalize_workdir(tmp_path)
    spec = _spec(tmp_path, hints=("CHK-0", "CHK-1"))  # CHK-1 covered by nothing
    assert vs.finalize(wd, spec, status=None, revision=None) == 2
    assert not (wd / "result.json").exists()


def test_fail_path_does_not_re_run_the_gate(tmp_path):
    # An early-fail workdir may hold no sidecars at all; running the gate there would turn a
    # routable fail into a BLOCKED.
    wd = tmp_path / "plan"
    wd.mkdir()
    rc = vs.finalize(
        wd,
        tmp_path / "nonexistent-spec",
        status="fail",
        revision=None,
        fail_reason="external reference missing: Design/specification/design.md",
    )
    assert rc == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["fail_reason"].startswith("external reference missing")
    assert env["artifacts"] == []


def test_enumerate_artifacts_fixed_set_present_only(tmp_path):
    wd = _finalize_workdir(tmp_path)
    (wd / "plan-review" / "decisions.md").write_text("User accepted TP-1: ...\n")
    arts = vs.enumerate_artifacts(wd)
    assert [a["path"] for a in arts] == [
        "verification-plan.md",
        "tb-scaffold.json",
        "sequences.json",
        "power-scenarios.json",
        "plan-review/review.md",
        "plan-review/decisions.md",
    ]
    assert all(set(a) == {"path"} for a in arts)  # the path IS the identity
    assert all((wd / a["path"]).is_file() for a in arts)


def test_enumerate_artifacts_omits_absent_decisions(tmp_path):
    # decisions.md exists only when the user accepted something a reviewer called blocking
    wd = _finalize_workdir(tmp_path)
    paths = [a["path"] for a in vs.enumerate_artifacts(wd)]
    assert "plan-review/review.md" in paths
    assert "plan-review/decisions.md" not in paths


# ── golden: lean shape + schema, against the real tpu_top run ────────────────
from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"


def _validate_envelope(env: dict) -> None:
    # Inline Registry: validate the in-memory envelope against
    # {envelope schema + simulation-plan result.schema} via Registry.
    env_schema = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (ROOT / "skills/simulation-plan/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        _ENVELOPE_URI, Resource.from_contents(env_schema)
    )
    Draft202012Validator(stage_schema, registry=registry).validate(env)


def test_golden_lean_against_real_tpu_top(tmp_path):
    import shutil

    wd = tmp_path / "simulation-plan"
    shutil.copytree(FIX / "simulation-plan-tpu_top", wd)
    rev = "rev 0.3 (rework r2): added apb_weight_load precondition to T-04 + T-07"
    # The plan fixture's covers[] resolve against the specification fixture's check hints —
    # the same pairing the real run had, so the re-run gate is exercised on real content.
    assert vs.build_result(wd, SPEC_FIX, status=None, revision=rev) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert env["stage_specific"] == {"revision": rev}
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {
        "verification-plan.md",
        "tb-scaffold.json",
        "sequences.json",
        "power-scenarios.json",
        "plan-review/review.md",
    }
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")
    _validate_envelope(env)


# ── finalize-wrapper exit-code BLOCKED semantics ──
def test_finalize_blocked_on_internal_raise(tmp_path):
    # missing tb-scaffold.json → the re-run gate reports it → exit 2 BLOCKED
    assert vs.finalize(tmp_path, _spec(tmp_path), status=None, revision=None) == 2
    assert not (tmp_path / "result.json").exists()


def test_finalize_blocked_on_empty_fail_reason(tmp_path):
    rc = vs.finalize(
        tmp_path, _spec(tmp_path), status="fail", revision=None, fail_reason="  "
    )
    assert rc == 2
    assert not (tmp_path / "result.json").exists()


def test_fail_reason_without_status_fail_is_blocked(tmp_path):
    # an unpaired --fail-reason is a caller slip about to invert a failure into a
    # computed pass — refused loudly, never silently discarded
    wd = _finalize_workdir(tmp_path)
    rc = vs.finalize(
        wd,
        _spec(tmp_path),
        status=None,
        revision=None,
        fail_reason="user rejected plan",
    )
    assert rc == 2
    assert not (wd / "result.json").exists()


def test_bare_status_fail_without_review_is_blocked(tmp_path):
    # A user reject can only follow the review, and the reviewer — not this caller — writes
    # that file, so requiring it is not the checked party vouching for itself.
    wd = _finalize_workdir(tmp_path, review=False)
    rc = vs.finalize(wd, _spec(tmp_path), status="fail", revision=None)
    assert rc == 2
    assert not (wd / "result.json").exists()


def test_earlyfail_seeded_workdir_carries_products(tmp_path):
    # on a seeded rework workdir the present-only enumeration carries the prior
    # products, so a promoted early fail cannot GC canonical down to a hollow view
    (tmp_path / "verification-plan.md").write_text("PLAN", encoding="utf-8")
    (tmp_path / "tb-scaffold.json").write_text("{}", encoding="utf-8")
    rc = vs.finalize(
        tmp_path,
        _spec(tmp_path),
        status="fail",
        revision=None,
        fail_reason="external reference missing: /x/design.md",
    )
    assert rc == 0
    env = json.loads((tmp_path / "result.json").read_text())
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {"verification-plan.md", "tb-scaffold.json"}
