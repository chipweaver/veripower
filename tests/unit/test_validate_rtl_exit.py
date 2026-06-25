# tests/unit/test_validate_rtl_exit.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/rtl-design/scripts/validate_rtl_exit.py"
_ANN = {"sgdc": {}, "sdc": {}}


def _setup(tmp_path, children, fresh, ledger):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "top", "children": children})
    )
    (tmp_path / "fresh.json").write_text(json.dumps(fresh))
    (tmp_path / ".child_reports.json").write_text(json.dumps(ledger))


def _run(tmp_path, top, check=False):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--top",
            top,
            "--fresh",
            str(tmp_path / "fresh.json"),
            "--ledger",
            str(tmp_path / ".child_reports.json"),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def test_pass_exactly_one_top_child(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {"leaf": {"status": "done"}, "topc": {"status": "done"}},
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["status"] == "pass"
    # Envelope shape: artifacts is a list of {"path": ...} objects (NOT flat strings).
    # Asserting on the object shape is what makes this test catch M1 instead of masking it.
    assert all(isinstance(a, dict) and "path" in a for a in v["artifacts"])
    paths = {a["path"] for a in v["artifacts"]}
    assert ".child_reports.json" in paths
    assert "filelist.txt" in paths and "README.md" in paths
    assert "leaf.sv" in paths and "top.sv" in paths


def test_fail_zero_top_children(tmp_path):
    _setup(
        tmp_path,
        [{"name": "leaf", "rtl_modules": ["leaf_m"]}],
        {"leaf": {"status": "done"}},
        {"leaf": {"files": ["leaf.sv"], "annotations": _ANN}},
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 1
    assert "covered by 0 children" in json.loads(r.stdout)["fail_reason"]


def test_fail_two_top_children(tmp_path):
    _setup(
        tmp_path,
        [{"name": "a", "rtl_modules": ["top"]}, {"name": "b", "rtl_modules": ["top"]}],
        {"a": {"status": "done"}, "b": {"status": "done"}},
        {
            "a": {"files": ["a.sv"], "annotations": _ANN},
            "b": {"files": ["b.sv"], "annotations": _ANN},
        },
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 1
    assert "covered by 2 children" in json.loads(r.stdout)["fail_reason"]


def test_fail_when_child_blocked(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {"status": "blocked", "reason": "iface incomplete"},
            "topc": {"status": "done"},
        },
        {"topc": {"files": ["top.sv"], "annotations": _ANN}},
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 1
    assert "blocked" in json.loads(r.stdout)["fail_reason"]


def test_fail_top_child_not_pure(tmp_path):
    """L2 purity: a top-integration child bundling a logic module fails (post phase)."""
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top", "wb_front"]},
        ],
        {"leaf": {"status": "done"}, "topc": {"status": "done"}},
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 1
    assert "not pure" in json.loads(r.stdout)["fail_reason"]


def _run_pre(tmp_path, top):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--top",
            top,
            "--phase",
            "pre",
        ],
        capture_output=True,
        text=True,
    )


def test_pre_phase_fails_bundled_top_manifest_only(tmp_path):
    """L2 pre-dispatch: --phase pre checks coverage+purity from manifest+top only (no reports)."""
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "top",
                "children": [
                    {"name": "leaf", "rtl_modules": ["leaf_m"]},
                    {"name": "topc", "rtl_modules": ["top", "wb_front"]},
                ],
            }
        )
    )
    r = _run_pre(tmp_path, "top")
    assert r.returncode == 1
    assert "not pure" in json.loads(r.stdout)["fail_reason"]


def test_pre_phase_fails_zero_coverage(tmp_path):
    """--phase pre with no covering child fails (coverage check, manifest-only)."""
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"module": "top", "children": [{"name": "leaf", "rtl_modules": ["leaf_m"]}]}
        )
    )
    r = _run_pre(tmp_path, "top")
    assert r.returncode == 1
    assert "covered by 0 children" in json.loads(r.stdout)["fail_reason"]


def test_pre_phase_passes_pure_top_manifest_only(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "top",
                "children": [
                    {"name": "leaf", "rtl_modules": ["leaf_m"]},
                    {"name": "topc", "rtl_modules": ["top"]},
                ],
            }
        )
    )
    r = _run_pre(tmp_path, "top")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "pass"
    assert json.loads(r.stdout)["artifacts"] == []


# ── finalize / build_result — exercised IN-PROCESS (Task 1/2/3) ──────────────
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
import validate_rtl_exit as ve  # noqa: E402

_SEM_CLEAR = {
    "schema_version": 1,
    "stage": "rtl-design",
    "module": "tpu_top",
    "reviewed_children": ["mac"],
    "verdict": "ok",
    "has_critical": False,
    "findings": [],
}


def _workdir(
    tmp_path, *, children=("mac",), top="tpu_top", semantic=_SEM_CLEAR, manifest=None
):
    """Build a minimal converged rtl-design workdir + a sibling spec manifest."""
    wd = tmp_path / "rtl-design"
    wd.mkdir()
    for c in children:
        (wd / f"{c}.v").write_text(f"module {c}; endmodule\n")
    (wd / f"{top}.v").write_text(f"module {top}; endmodule\n")
    (wd / "filelist.txt").write_text(
        "\n".join(f"{c}.v" for c in children) + f"\n{top}.v\n"
    )
    (wd / "README.md").write_text(f"**Top module**: {top}\n")

    # ledger (.child_reports.json) — ledger_io.load_ledger REQUIRES per record {files, annotations}
    # with annotations.sgdc + annotations.sdc sub-blocks. NO `status` key (status lives in fresh).
    def _ann():
        return {"sgdc": {}, "sdc": {}}

    ledger = {
        c: {"files": [f"{c}.v"], "annotations": _ann(), "incdirs": []} for c in children
    }
    ledger[top] = {"files": [f"{top}.v"], "annotations": _ann(), "incdirs": []}
    (wd / ".child_reports.json").write_text(json.dumps(ledger))
    # fresh_reports.json (all done) — validate_rtl_exit --phase post hard-requires --fresh.
    (wd / "fresh_reports.json").write_text(
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
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "rtl-design",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["top_module"] == "tpu_top"
    assert ss["semantic_gate"] == {
        "gate": "clear",
        "flagged": [],
        "loci": {"rtl": [], "spec": []},
    }
    assert (
        "note" not in ss and "fail_reason" not in ss
    )  # lean shape: free-text note dropped
    # artifacts[] came from the exit gate (the .v + the three fixed files) + semantic-review.json
    paths = {a["path"] for a in env["artifacts"]}
    assert {
        "mac.v",
        "tpu_top.v",
        "filelist.txt",
        "README.md",
        ".child_reports.json",
    } <= paths
    assert "semantic-review.json" in paths and "result.json" not in paths


def test_build_result_fail_on_semantic_trip(tmp_path):
    sem = {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": "tpu_top",
        "reviewed_children": ["mac"],
        "verdict": "concerns",
        "has_critical": True,
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


def test_finalize_cli_does_not_break_legacy_exit_cli(tmp_path):
    # the legacy bare-flag invocation still runs the exit gate (no subcommand) — back-compat guard.
    wd, manifest = _workdir(tmp_path)
    assert (
        ve.main(
            [
                "validate_rtl_exit.py",
                "--manifest",
                str(manifest),
                "--top",
                "tpu_top",
                "--fresh",
                str(wd / "fresh_reports.json"),
                "--ledger",
                str(wd / ".child_reports.json"),
            ]
        )
        == 0
    )


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
    # INLINE Registry (not the frontend-signoff-bound helper): the rtl-design stage schema
    # $ref's the envelope by $id, so resolve it via a local Registry.
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
    assert ss["top_module"] == "tpu_top"
    # semantic_gate — exact to the real run (clear: the one over-engineering finding never gates)
    assert ss["semantic_gate"] == {
        "gate": "clear",
        "flagged": [],
        "loci": {"rtl": [], "spec": []},
    }
    # artifacts — the real 8-entry set: 4 .v + filelist + README + ledger + semantic-review
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {
        "fifo.v",
        "mac.v",
        "systolic_reg.v",
        "tpu_top.v",
        "filelist.txt",
        "README.md",
        ".child_reports.json",
        "semantic-review.json",
    }
    assert "result.json" not in paths
    # lean: free-text note DROPPED; produced_at normalized; schema-valid
    assert "note" not in ss
    assert env["produced_at"].endswith("Z")
    _validate_envelope(env)
