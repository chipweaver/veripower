# tests/unit/test_rtl_result.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
from rtl import result as ve  # noqa: E402

_REVIEW = "Read §2 against the RTL; it holds. Nothing blocks.\n"


def _write_state(d, ledger):
    """rtl-design's two sidecars from the merged {child: {files, incdirs?, annotations}} shape."""
    import json as _json

    files, anns = {}, {}
    for name, rec in ledger.items():
        e = {"files": rec.get("files", [])}
        if rec.get("incdirs"):
            e["incdirs"] = rec["incdirs"]
        files[name] = e
        anns[name] = rec.get("annotations", {})
    (d / "rtl-files.json").write_text(_json.dumps(files))
    (d / "constraint-annotations.json").write_text(_json.dumps(anns))


def _workdir(
    tmp_path, *, children=("mac",), top="tpu_top", reviews=True, manifest=None
):
    """Build a minimal converged rtl-design workdir + a sibling spec manifest."""
    wd = tmp_path / "rtl-design"
    wd.mkdir()
    for c in children:
        (wd / f"{c}.v").write_text(f"module {c}; endmodule\n")
    (wd / f"{top}.v").write_text(f"module {top}; endmodule\n")

    def _ann():
        return {
            "sgdc": {
                "sync_cell": [],
                "reset_synchronizer": [],
                "set_case_analysis": [],
                "quasi_static": [],
            },
            "sdc": {
                "create_generated_clock": [],
                "set_multicycle_path": [],
                "set_false_path": [],
            },
        }

    ledger = {
        c: {"files": [f"{c}.v"], "annotations": _ann(), "incdirs": []} for c in children
    }
    ledger[top] = {"files": [f"{top}.v"], "annotations": _ann(), "incdirs": []}
    _write_state(wd, ledger)
    # reaped-children.json (all done) — the post exit-gate hard-requires reaped-children.json.
    (wd / "reaped-children.json").write_text(
        json.dumps({n: {"status": "done"} for n in ledger})
    )
    # spec manifest: top-integration child is pure (rtl_modules == [top]); each leaf covers itself.
    man = manifest or {
        "module": top,
        "children": [
            {"name": c, "doc": f"{c}.md", "rtl_modules": [c]} for c in children
        ]
        + [{"name": "topc", "doc": "topc.md", "rtl_modules": [top]}],
    }
    spec = tmp_path / "Design" / "specification"
    spec.mkdir(parents=True)
    (spec / "manifest.json").write_text(json.dumps(man))
    if reviews:
        (wd / "semantic-review").mkdir(exist_ok=True)
        for c in man["children"]:
            (wd / "semantic-review" / f"{c['name']}.md").write_text(_REVIEW)
    return wd, spec / "manifest.json"


def test_build_result_pass_lean_shape(tmp_path):
    wd, manifest = _workdir(tmp_path)
    assert ve.build_result(wd, module="tpu_top", top="tpu_top", manifest=manifest) == 0
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["module"]) == (
        "rtl-design",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    # A passing envelope carries nothing: no verdict is reduced from the reviews.
    assert env["stage_specific"] == {}
    paths = {a["path"] for a in env["artifacts"]}
    assert {
        "mac.v",
        "tpu_top.v",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review/mac.md",
        "semantic-review/topc.md",
    } <= paths
    assert "result.json" not in paths


def test_pass_refused_while_a_child_review_is_missing(tmp_path, capsys):
    # The exit requirement, and the only mechanical part of it: nothing else in this stage
    # checks that the intent review happened, and there is no in-stage human gate to notice.
    # What a review SAYS stays the stage's judgment; that it EXISTS for every child does not.
    wd, manifest = _workdir(tmp_path)
    (wd / "semantic-review" / "mac.md").unlink()
    assert ve.finalize(wd, "tpu_top", "tpu_top", manifest) == 2
    assert "semantic-review/mac.md" in capsys.readouterr().err
    assert not (wd / "result.json").exists()


def test_build_result_fail_on_exit_topology_verbatim(tmp_path):
    # Manifest where the top-integration child bundles a logic module -> not pure -> exit fail.
    bad_manifest = {
        "module": "tpu_top",
        "children": [
            {"name": "mac", "doc": "mac.md", "rtl_modules": ["mac"]},
            {"name": "topc", "doc": "topc.md", "rtl_modules": ["tpu_top", "mac"]},
        ],
    }  # impure
    wd, manifest = _workdir(tmp_path, manifest=bad_manifest)
    assert ve.build_result(wd, module="tpu_top", top="tpu_top", manifest=manifest) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert (
        "not pure" in env["stage_specific"]["fail_reason"]
    )  # verbatim from the exit gate


# ── golden test against the real tpu_top run ─────────────────────────────────
from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"


def _validate_envelope(env: dict) -> None:
    # INLINE Registry: the rtl-design stage schema $ref's the envelope by $id, so
    # resolve it via a local Registry.
    env_schema = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (ROOT / "skills/rtl-design/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        _ENVELOPE_URI, Resource.from_contents(env_schema)
    )
    Draft202012Validator(stage_schema, registry=registry).validate(env)


def test_golden_lean_against_real_tpu_top(tmp_path):
    import shutil

    FIX = Path(__file__).resolve().parent / "fixtures" / "rtl-design-tpu_top"
    base = tmp_path / "rtl"
    shutil.copytree(FIX, base)
    wd = base / "rtl-design"
    manifest = base / "Design" / "specification" / "manifest.json"
    assert ve.build_result(wd, module="tpu_top", top="tpu_top", manifest=manifest) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "pass"
    assert ss == {}
    # artifacts — 4 .v + the two sidecars + one review per manifest child
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {
        "fifo.v",
        "mac.v",
        "systolic_reg.v",
        "tpu_top.v",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review/fifo.md",
        "semantic-review/mac.md",
        "semantic-review/systolic_reg.md",
        "semantic-review/tpu_top.md",
    }
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")
    _validate_envelope(env)


def test_build_result_pre_dispatch_coverage_fail_routes_through_finalize(tmp_path):
    # A pre-dispatch coverage fail (no fan-out yet -> no ledger, no
    # reaped-children.json) routes through finalize and surfaces the REAL coverage reason, not
    # the generic "requires reaped-children.json and the ledger" pre-guard message. This exercises
    # partition.post_verdict's coverage short-circuit (status=fail AND no ledger).
    wd = tmp_path / "rtl-design"
    wd.mkdir()  # empty: no ledger, no reaped-children.json (pre-dispatch state)
    man = {  # top module covered by 0 children -> coverage fail
        "module": "tpu_top",
        "children": [{"name": "mac", "doc": "mac.md", "rtl_modules": ["mac"]}],
    }
    spec = tmp_path / "Design" / "specification"
    spec.mkdir(parents=True)
    manifest = spec / "manifest.json"
    manifest.write_text(json.dumps(man))

    assert ve.build_result(wd, module="tpu_top", top="tpu_top", manifest=manifest) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    fr = env["stage_specific"]["fail_reason"]
    assert "covered by 0 children" in fr  # the real coverage reason, surfaced
    assert (
        "requires reaped-children.json" not in fr
    )  # NOT the generic pre-guard message
    _validate_envelope(env)  # schema-valid status=fail envelope


# ── finalize() BLOCKED wrapper + CLI dispatch ────────────────────────────────
def test_finalize_blocked_on_internal_raise(tmp_path, monkeypatch):
    # finalize() wraps build_result(): any internal raise -> exit 2 (BLOCKED), never
    # status=fail. (The deleted main() owned this except; it moves to finalize().)
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(ve, "build_result", boom)
    assert ve.finalize(tmp_path, "tpu_top", "tpu_top", tmp_path / "manifest.json") == 2


def test_artifacts_are_full_roster_on_a_subset_reap(tmp_path):
    # A repair round reaps only the re-dispatched children, so
    # reaped-children.json is a subset. artifacts[] is enumerated from the two sidecars (the full
    # merged ledger), never from the reaped set — which is why no full-roster rebuild of
    # reaped-children.json is needed before finalize.
    wd, manifest = _workdir(tmp_path, children=("mac", "ctrl"))
    (wd / "reaped-children.json").write_text(json.dumps({"mac": {"status": "done"}}))
    assert ve.build_result(wd, module="tpu_top", top="tpu_top", manifest=manifest) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert {"mac.v", "ctrl.v", "tpu_top.v"} <= {a["path"] for a in env["artifacts"]}


def test_fail_reason_writes_the_envelope_and_keeps_the_readable_baseline(tmp_path):
    # The build-error exit: reaped-children.json is malformed, so no verdict is derivable, but the
    # carried sidecars are fine. finalize must write the fail envelope itself (never the agent by
    # hand — a hand-written envelope that violates result.schema.json reaps as blocked, not as a
    # routable fail) AND keep enumerating the readable baseline, because promote treats artifacts[]
    # as the new canonical view and deletes what it omits.
    wd, manifest = _workdir(tmp_path)
    (wd / "reaped-children.json").write_text("{ not json")
    assert (
        ve.finalize(wd, "tpu_top", "tpu_top", manifest, fail_reason="reports malformed")
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"] == {"fail_reason": "reports malformed"}
    assert {
        "mac.v",
        "tpu_top.v",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review/mac.md",
        "semantic-review/topc.md",
    } == {a["path"] for a in env["artifacts"]}
    _validate_envelope(env)


def test_fail_reason_with_unreadable_sidecars_still_keeps_the_reviews(tmp_path):
    # Nothing is knowable about the ledger, so no .v is guessed at. The reviews are read
    # straight off disk, and they are the evidence for the failure, so they still promote.
    wd, manifest = _workdir(tmp_path)
    (wd / "rtl-files.json").write_text("{ not json")
    assert (
        ve.finalize(wd, "tpu_top", "tpu_top", manifest, fail_reason="sidecar broken")
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert {a["path"] for a in env["artifacts"]} == {
        "semantic-review/mac.md",
        "semantic-review/topc.md",
    }


def test_finalize_missing_required_flag_is_blocked(tmp_path):
    MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"
    # missing --manifest -> argparse exit 2
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(tmp_path),
            "--module",
            "tpu_top",
            "--top",
            "tpu_top",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2  # argparse: missing --manifest


def test_finalize_cli_happy_path(tmp_path):
    # End-to-end through _cmd_finalize (lazy handler import + arg mapping), not just
    # in-process build_result(). A handler typo would pass every other test but fail here.
    wd, manifest = _workdir(tmp_path)
    MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--module",
            "tpu_top",
            "--top",
            "tpu_top",
            "--manifest",
            str(manifest),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"], env["module"]) == (
        "rtl-design",
        "pass",
        "tpu_top",
    )
