# tests/unit/test_rtl_result.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
from rtl import result as ve  # noqa: E402

_SEM_CLEAR = {
    "stage": "rtl-design",
    "module": "tpu_top",
    "reviewed_children": ["mac"],
    "findings": [],
}


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
    tmp_path, *, children=("mac",), top="tpu_top", semantic=_SEM_CLEAR, manifest=None
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
    (wd / "semantic-review.json").write_text(json.dumps(semantic))
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
    ss = env["stage_specific"]
    assert ss["semantic_gate"] == {
        "gate": "clear",
        "flagged": [],
        "loci": {"rtl": [], "spec": []},
        "spec_confidence": None,
    }
    assert (
        "note" not in ss and "fail_reason" not in ss
    )  # lean shape: free-text note dropped
    # artifacts[] came from the exit gate (the .v + the three fixed files) + semantic-review.json
    paths = {a["path"] for a in env["artifacts"]}
    assert {
        "mac.v",
        "tpu_top.v",
        "rtl-files.json",
        "constraint-annotations.json",
    } <= paths
    assert "semantic-review.json" in paths and "result.json" not in paths


def test_build_result_fail_on_semantic_trip(tmp_path):
    sem = {
        "stage": "rtl-design",
        "module": "tpu_top",
        "reviewed_children": ["mac"],
        "findings": [
            {
                "child": "mac",
                "category": "wrong-behavior",
                "severity": "critical",
                "fix_locus": "rtl",
                "location": "L1",
                "summary": "wrong accumulate",
            }
        ],
    }
    wd, manifest = _workdir(tmp_path, semantic=sem)
    assert ve.build_result(wd, module="tpu_top", top="tpu_top", manifest=manifest) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["semantic_gate"]["gate"] == "trip"
    assert "mac" in env["stage_specific"]["fail_reason"]


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
    assert (
        "semantic_gate" not in env["stage_specific"]
    )  # never reached the semantic gate


# ── golden test against the real tpu_top run (Task 3) ────────────────────────
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
    # semantic_gate — exact to the real run (clear: the one over-engineering finding never gates)
    assert ss["semantic_gate"] == {
        "gate": "clear",
        "flagged": [],
        "loci": {"rtl": [], "spec": []},
        "spec_confidence": None,
    }
    # artifacts — the real 7-entry set: 4 .v + the two sidecars + semantic-review
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {
        "fifo.v",
        "mac.v",
        "systolic_reg.v",
        "tpu_top.v",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review.json",
    }
    assert "result.json" not in paths
    # lean: free-text note DROPPED; produced_at normalized; schema-valid
    assert "note" not in ss
    assert env["produced_at"].endswith("Z")
    _validate_envelope(env)


def test_build_result_pre_dispatch_coverage_fail_routes_through_finalize(tmp_path):
    # F-A: a pre-dispatch check-partition coverage fail (no fan-out yet -> no ledger, no
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
    assert (
        "semantic_gate" not in env["stage_specific"]
    )  # never reached the semantic gate
    _validate_envelope(env)  # schema-valid status=fail envelope


# ── New: finalize() BLOCKED wrapper + CLI dispatch ───────────────────────────
def test_finalize_blocked_on_internal_raise(tmp_path, monkeypatch):
    # finalize() wraps build_result(): any internal raise -> exit 2 (BLOCKED), never
    # status=fail. (The deleted main() owned this except; it moves to finalize().)
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(ve, "build_result", boom)
    assert ve.finalize(tmp_path, "tpu_top", "tpu_top", tmp_path / "manifest.json") == 2


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


def test_gating_categories_match_the_schema_enum():
    # result.schema.json's $comment says flagged.category is "kept in sync with
    # _GATING_CATEGORIES in rtl/review.py". That is the only thing that held them together;
    # this is the check. A category added to one side and not the other would either be
    # dropped from the envelope or rejected by it.
    from rtl.review import _GATING_CATEGORIES

    schema = json.loads(
        (ROOT / "skills/rtl-design/references/result.schema.json").read_text()
    )
    ss = schema["allOf"][1]["properties"]["stage_specific"]["properties"]
    enum = ss["semantic_gate"]["properties"]["flagged"]["items"]["properties"][
        "category"
    ]["enum"]
    assert set(enum) == _GATING_CATEGORIES
