# tests/unit/test_rtl_result.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
from rtl import result as ve  # noqa: E402

REVIEW = "Read §2 against the RTL; it holds. Nothing blocks.\n"


def write_state(d, ledger):
    """rtl-design's two sidecars from the merged {child: {files, incdirs?, annotations}} shape."""

    files, anns = {"files": [], "incdirs": []}, {}
    for name, rec in ledger.items():
        files["files"].extend(rec.get("files", []))
        files["incdirs"].extend(rec.get("incdirs", []))
        anns[name] = rec.get("annotations", {})
    (d / "rtl-files.json").write_text(json.dumps(files))
    (d / "constraint-annotations.json").write_text(json.dumps(anns))


def workdir(tmp_path, *, children=("mac",), top="dut_top", reviews=True):
    """Build a minimal converged rtl-design workdir."""
    wd = tmp_path / "rtl-design"
    (wd / "src").mkdir(parents=True)
    for c in children:
        (wd / f"src/{c}.v").write_text(f"module {c}; endmodule\n")
    (wd / f"src/{top}.v").write_text(f"module {top}; endmodule\n")

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

    # The ledger's keys ARE the roster: the top-integration child is `topc` and the file it
    # authored is <top>.v.
    names = list(children) + ["topc"]
    ledger = {
        c: {"files": [f"src/{c}.v"], "annotations": _ann(), "incdirs": []}
        for c in children
    }
    ledger["topc"] = {
        "files": [f"src/{top}.v"],
        "annotations": _ann(),
        "incdirs": [],
    }
    write_state(wd, ledger)
    if reviews:
        (wd / "semantic-review").mkdir(exist_ok=True)
        for c in names:
            (wd / "semantic-review" / f"{c}.md").write_text(REVIEW)
    return wd


def test_finalize_pass_lean_shape(tmp_path):
    wd = workdir(tmp_path)
    assert ve.finalize(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "rtl-design"
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    # A passing envelope carries nothing: no verdict is reduced from the reviews.
    assert env["stage_specific"] == {}
    paths = {a["path"] for a in env["artifacts"]}
    assert {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review",
    } <= paths
    assert "result.json" not in paths
    validate_envelope(env)


def test_reviews_are_enumerated_off_disk_not_off_the_roster(tmp_path):
    # Review layout is chosen by the stage; the complete directory is delivered.
    wd = workdir(tmp_path)
    (wd / "semantic-review" / "mac.md").unlink()
    (wd / "semantic-review" / "topc.md").rename(wd / "semantic-review" / "mac+topc.md")
    assert ve.finalize(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert "semantic-review" in {a["path"] for a in env["artifacts"]}
    assert (wd / "semantic-review" / "mac+topc.md").is_file()


def test_result_writer_leaves_review_judgment_to_the_stage_owner(tmp_path):
    # This result writer validates RTL artifacts. The stage owner reports incomplete
    # review with --fail-reason; absence of that report is not a semantic review.
    wd = workdir(tmp_path, reviews=False)
    assert ve.finalize(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert not [a for a in env["artifacts"] if a["path"].startswith("semantic-")]


def test_pass_refused_over_a_file_no_child_wrote(tmp_path, capsys):
    # artifacts[] is the new canonical view; promote hardlinks each entry and raises on the
    # first absent one, before any outcome event lands. Named here, where a re-dispatch fixes it.
    wd = workdir(tmp_path)
    (wd / "src/mac.v").unlink()
    assert ve.finalize(wd) == 2
    assert "src/mac.v" in capsys.readouterr().err
    assert not (wd / "result.json").exists()


# Result-schema checks.
from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"


def validate_envelope(env: dict) -> None:
    # INLINE Registry: the rtl-design stage schema $ref's the envelope by $id, so
    # resolve it via a local Registry.
    env_schema = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (ROOT / "skills/rtl-design/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        ENVELOPE_URI, Resource.from_contents(env_schema)
    )
    Draft202012Validator(stage_schema, registry=registry).validate(env)


def test_a_child_dropped_from_the_sidecars_leaves_its_rtl_unclaimed(tmp_path):
    # The sidecars ARE the roster now, so dropping a child does not contradict anything — the
    # round simply ships less. What it must not do is ship a canonical view that still claims
    # the dropped child's file: artifacts[] is the new canonical view and promote deletes what
    # it omits, so src/ stays whole while rtl-files.json stops naming that file.
    wd = workdir(tmp_path, children=("mac", "ctrl"))
    files = json.loads((wd / "rtl-files.json").read_text())
    files["files"].remove("src/ctrl.v")
    (wd / "rtl-files.json").write_text(json.dumps(files))
    annotations = json.loads((wd / "constraint-annotations.json").read_text())
    del annotations["ctrl"]
    (wd / "constraint-annotations.json").write_text(json.dumps(annotations))
    assert ve.finalize(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert {a["path"] for a in env["artifacts"]} == {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review",
    }
    assert "src/ctrl.v" not in json.loads((wd / "rtl-files.json").read_text())["files"]


def test_finalize_on_an_empty_workdir_is_blocked(tmp_path, capsys):
    # Nothing authored yet: the sidecars are absent, so no verdict is derivable. That is a broken
    # run, not a routable fail — BLOCKED writes no envelope, so nothing promotes over canonical.
    wd = tmp_path / "rtl-design"
    (wd / "src").mkdir(parents=True)
    spec = tmp_path / "Design" / "specification"
    spec.mkdir(parents=True)
    manifest = spec / "manifest.json"
    manifest.write_text(json.dumps({"module": "dut_top"}))
    assert ve.finalize(wd) == 2
    assert "rtl-files.json" in capsys.readouterr().err
    assert not (wd / "result.json").exists()


# ── finalize() BLOCKED wrapper + CLI dispatch ────────────────────────────────


def test_artifacts_are_full_roster_on_a_subset_round(tmp_path):
    # A repair round re-authors only some children and overlays them onto the carried sidecars,
    # so artifacts[] stays the full roster and the children this round did not touch keep their
    # place in canonical.
    wd = workdir(tmp_path, children=("mac", "ctrl"))
    assert ve.finalize(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert "src" in {a["path"] for a in env["artifacts"]}


def test_fail_reason_writes_the_envelope_and_keeps_the_readable_baseline(tmp_path):
    # The caller-reported exit: a child reported BLOCKED, so no on-disk state expresses the
    # failure, but the carried sidecars are fine. finalize must write the fail envelope itself
    # (never the agent by hand — a hand-written envelope that violates result.schema.json reaps
    # as blocked, not as a routable fail) AND keep enumerating the readable baseline, because
    # promote treats artifacts[] as the new canonical view and deletes what it omits.
    wd = workdir(tmp_path)
    assert ve.finalize(wd, fail_reason="child mac blocked") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"] == {"fail_reason": "child mac blocked"}
    assert {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review",
    } == {a["path"] for a in env["artifacts"]}
    validate_envelope(env)


def test_failed_delivery_preserves_invalid_inputs_and_reviews(tmp_path):
    # Invalid input is failure evidence, not a reason to erase the existing RTL tree.
    wd = workdir(tmp_path)
    (wd / "rtl-files.json").write_text("{ not json")
    assert ve.finalize(wd, fail_reason="sidecar broken") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert {a["path"] for a in env["artifacts"]} == {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review",
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
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2  # argparse: missing --manifest


def test_finalize_cli_happy_path(tmp_path):
    # End-to-end through the finalize CLI (lazy handler import + arg mapping), not just
    # in-process finalize(). A handler typo would pass every other test but fail here.
    wd = workdir(tmp_path)
    MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"]) == ("rtl-design", "pass")


# ---------- the artifacts enumeration ----------


ANN = {
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


def sidecars(tmp_path, files, *, write_rtl=True):
    (tmp_path / "rtl-files.json").write_text(json.dumps(files))
    (tmp_path / "constraint-annotations.json").write_text(
        json.dumps({"implementation": ANN})
    )
    if write_rtl:
        for f in files["files"]:
            (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / f).write_text("module m; endmodule\n")


def test_successful_delivery_requires_both_sidecars(tmp_path):
    assert ve.finalize(tmp_path) == 2
    assert not (tmp_path / "result.json").exists()


def test_successful_delivery_requires_all_listed_sources(tmp_path, capsys):
    sidecars(tmp_path, {"files": ["src/leaf.v", "src/top.v"]}, write_rtl=False)
    assert ve.finalize(tmp_path) == 2
    assert "src/leaf.v" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


def test_delivery_covers_unlisted_headers_in_the_source_tree(tmp_path):
    sidecars(tmp_path, {"files": ["src/leaf.v", "src/top.v"]})
    (tmp_path / "src/extra.vh").write_text("// included by a source file\n")
    assert ve.finalize(tmp_path) == 0
    result = json.loads((tmp_path / "result.json").read_text())
    assert {artifact["path"] for artifact in result["artifacts"]} == {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
    }


def test_failed_delivery_preserves_a_partial_source_tree(tmp_path):
    sidecars(tmp_path, {"files": ["src/leaf.v", "src/top.v"]})
    (tmp_path / "src/leaf.v").unlink()
    assert ve.finalize(tmp_path, fail_reason="leaf implementation missing") == 0
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["status"] == "fail"
    assert {artifact["path"] for artifact in result["artifacts"]} == {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
    }
