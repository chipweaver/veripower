# tests/unit/test_rtl_result.py
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
from rtl import result as ve  # noqa: E402
from rtl._ledger import LedgerError  # noqa: E402
from rtl.result import exit_artifacts, ledger_artifacts  # noqa: E402

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


def _workdir(tmp_path, *, children=("mac",), top="dut_top", reviews=True):
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
    _write_state(wd, ledger)
    if reviews:
        (wd / "semantic-review").mkdir(exist_ok=True)
        for c in names:
            (wd / "semantic-review" / f"{c}.md").write_text(_REVIEW)
    return wd


def test_build_result_pass_lean_shape(tmp_path):
    wd = _workdir(tmp_path)
    assert ve.build_result(wd) == 0
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


def test_reviews_are_enumerated_off_disk_not_off_the_roster(tmp_path):
    # How the wave splits the RTL between its reviewers is the stage's call, so nothing here
    # coverage counts, and the review directory is delivered whatever the wave called the files
    # in it — the tree is the only route by which the oracle ever sees them.
    wd = _workdir(tmp_path)
    (wd / "semantic-review" / "mac.md").unlink()
    (wd / "semantic-review" / "topc.md").rename(wd / "semantic-review" / "mac+topc.md")
    assert ve.build_result(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert "semantic-review" in {a["path"] for a in env["artifacts"]}
    assert (wd / "semantic-review" / "mac+topc.md").is_file()


def test_pass_over_an_unreviewed_workdir_is_the_kernels_call_not_this_gate(tmp_path):
    # finalize does not check that any review landed: the kernel already refuses to pin an
    # oracle whose selector matched nothing, and the signoff gate blocks while the grade is
    # proposed. A second copy here would only fail the round earlier for the same defect.
    wd = _workdir(tmp_path, reviews=False)
    assert ve.build_result(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert not [a for a in env["artifacts"] if a["path"].startswith("semantic-")]


def test_pass_refused_over_a_file_no_child_wrote(tmp_path, capsys):
    # artifacts[] is the new canonical view; promote hardlinks each entry and raises on the
    # first absent one, before any outcome event lands. Named here, where a re-dispatch fixes it.
    wd = _workdir(tmp_path)
    (wd / "src/mac.v").unlink()
    assert ve.finalize(wd) == 2
    assert "src/mac.v" in capsys.readouterr().err
    assert not (wd / "result.json").exists()


# ── golden test against a real run ───────────────────────────────────────────
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


def test_golden_lean_against_a_real_run(tmp_path):
    import shutil

    FIX = Path(__file__).resolve().parent / "fixtures" / "rtl-design-golden"
    base = tmp_path / "rtl"
    shutil.copytree(FIX, base)
    wd = base / "rtl-design"
    assert ve.build_result(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "pass"
    assert ss == {}
    # artifacts — the RTL tree, the two sidecars, and the review tree
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review",
    }
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")
    _validate_envelope(env)


def test_a_child_dropped_from_the_sidecars_leaves_its_rtl_unclaimed(tmp_path):
    # The sidecars ARE the roster now, so dropping a child does not contradict anything — the
    # round simply ships less. What it must not do is ship a canonical view that still claims
    # the dropped child's file: artifacts[] is the new canonical view and promote deletes what
    # it omits, so src/ stays whole while rtl-files.json stops naming that file.
    wd = _workdir(tmp_path, children=("mac", "ctrl"))
    for name in ("rtl-files.json", "constraint-annotations.json"):
        doc = json.loads((wd / name).read_text())
        del doc["ctrl"]
        (wd / name).write_text(json.dumps(doc))
    assert ve.finalize(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert {a["path"] for a in env["artifacts"]} == {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
        "semantic-review",
    }
    assert "ctrl" not in json.loads((wd / "rtl-files.json").read_text())


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
def test_finalize_blocked_on_internal_raise(tmp_path, monkeypatch):
    # finalize() wraps build_result(): any internal raise -> exit 2 (BLOCKED), never
    # status=fail. (The deleted main() owned this except; it moves to finalize().)
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(ve, "build_result", boom)
    assert ve.finalize(tmp_path) == 2


def test_artifacts_are_full_roster_on_a_subset_round(tmp_path):
    # A repair round re-authors only some children and overlays them onto the carried sidecars,
    # so artifacts[] stays the full roster and the children this round did not touch keep their
    # place in canonical.
    wd = _workdir(tmp_path, children=("mac", "ctrl"))
    assert ve.build_result(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert "src" in {a["path"] for a in env["artifacts"]}


def test_fail_reason_writes_the_envelope_and_keeps_the_readable_baseline(tmp_path):
    # The caller-reported exit: a child reported BLOCKED, so no on-disk state expresses the
    # failure, but the carried sidecars are fine. finalize must write the fail envelope itself
    # (never the agent by hand — a hand-written envelope that violates result.schema.json reaps
    # as blocked, not as a routable fail) AND keep enumerating the readable baseline, because
    # promote treats artifacts[] as the new canonical view and deletes what it omits.
    wd = _workdir(tmp_path)
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
    _validate_envelope(env)


def test_fail_reason_with_unreadable_sidecars_still_keeps_the_reviews(tmp_path):
    # Nothing is knowable about the ledger, so no .v is guessed at. The reviews are read
    # straight off disk, and they are the evidence for the failure, so they still promote.
    wd = _workdir(tmp_path)
    (wd / "rtl-files.json").write_text("{ not json")
    assert ve.finalize(wd, fail_reason="sidecar broken") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert {a["path"] for a in env["artifacts"]} == {
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
    # End-to-end through _cmd_finalize (lazy handler import + arg mapping), not just
    # in-process build_result(). A handler typo would pass every other test but fail here.
    wd = _workdir(tmp_path)
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


_ANN = {
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


def _sidecars(tmp_path, files, *, write_rtl=True):
    (tmp_path / "rtl-files.json").write_text(json.dumps(files))
    (tmp_path / "constraint-annotations.json").write_text(
        json.dumps({name: _ANN for name in files})
    )
    if write_rtl:
        for rec in files.values():
            for f in rec["files"]:
                (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
                (tmp_path / f).write_text("module m; endmodule\n")


def test_exit_artifacts_raises_when_a_sidecar_is_absent(tmp_path):
    # No sidecars means no artifacts[] is derivable at all. That is a broken run, not a routable
    # fail: LedgerError reaches finalize, which exits 2 BLOCKED without writing an envelope,
    # so nothing promotes over canonical.
    with pytest.raises(LedgerError):
        exit_artifacts(tmp_path)


def test_exit_artifacts_raises_on_a_file_no_child_wrote(tmp_path):
    # promote hardlinks every artifacts[] entry and raises on the first absent one — BEFORE the
    # outcome event is appended, so the round would hang with nothing in the log to repair from.
    # Named here instead, where re-dispatching the owning child still fixes it.
    _sidecars(
        tmp_path,
        {"leaf": {"files": ["src/leaf.v"]}, "topc": {"files": ["src/top.v"]}},
        write_rtl=False,
    )
    with pytest.raises(LedgerError, match="src/leaf.v"):
        exit_artifacts(tmp_path)


def test_exit_artifacts_is_the_tree_and_both_sidecars(tmp_path):
    # The RTL leaves as ONE tree entry, never a file enumeration: the tree's version is a merkle
    # over everything under it, so a header, a subdirectory and a file the sidecars do not name
    # are all inside the version a consumer records.
    _sidecars(
        tmp_path, {"leaf": {"files": ["src/leaf.v"]}, "topc": {"files": ["src/top.v"]}}
    )
    assert {a["path"] for a in exit_artifacts(tmp_path)} == {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
    }


def test_ledger_artifacts_survives_a_file_the_sidecars_name_and_nobody_wrote(tmp_path):
    # The caller-reported fail path must still write an envelope over a workdir no verdict can be
    # derived from. It lists the tree, so a file the sidecars name and no child wrote cannot make
    # promote raise — the entry promote hardlinks is the directory, whatever is inside it.
    _sidecars(
        tmp_path, {"leaf": {"files": ["src/leaf.v"]}, "topc": {"files": ["src/top.v"]}}
    )
    (tmp_path / "src/leaf.v").unlink()
    assert {a["path"] for a in ledger_artifacts(tmp_path)} == {
        "src",
        "rtl-files.json",
        "constraint-annotations.json",
    }
