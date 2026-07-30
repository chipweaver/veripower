# tests/unit/test_rtl_assemble.py
"""rtl assemble verb — the two sidecars plus the post exit-gate in one idempotent verb.

Covers the assemble CLI end-to-end: what lands in rtl-files.json / constraint-annotations.json,
the post-gate verdict on stdout, and the build-error path (stderr + NO stdout verdict), which
the main thread distinguishes.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"
sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
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


def _write_state(d, ledger):
    """rtl-design's two sidecars from the merged {child: {files, incdirs?, annotations}} shape."""
    files, anns = {}, {}
    for name, rec in ledger.items():
        e = {"files": rec.get("files", [])}
        if rec.get("incdirs"):
            e["incdirs"] = rec["incdirs"]
        files[name] = e
        anns[name] = rec.get("annotations", {})
    (d / "rtl-files.json").write_text(json.dumps(files))
    (d / "constraint-annotations.json").write_text(json.dumps(anns))


def _read_state(d):
    """The merged view, the inverse of _write_state."""
    files = json.loads((d / "rtl-files.json").read_text())
    anns = json.loads((d / "constraint-annotations.json").read_text())
    return {n: {**rec, "annotations": anns[n]} for n, rec in files.items()}


def _manifest(*children):
    return {"module": "top", "children": list(children)}


def _setup(tmp_path, *, fresh, children):
    wd = tmp_path / "runs" / "1"
    wd.mkdir(parents=True)
    (wd / "reaped-children.json").write_text(json.dumps(fresh))
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest(*children)))
    return wd, tmp_path / "manifest.json"


def _run(wd, manifest, top="top", seeded=False):
    cmd = [
        "python3",
        str(MAIN),
        "assemble",
        "--workdir",
        str(wd),
        "--manifest",
        str(manifest),
        "--top",
        top,
    ]
    if seeded:
        cmd.append("--seeded")
    return subprocess.run(cmd, capture_output=True, text=True)


def test_assemble_first_run_strips_status(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "done", "files": ["leaf.v"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 0, r.stderr
    ledger = _read_state(wd)
    assert set(ledger) == {"leaf", "topc"}
    assert "status" not in ledger["leaf"]  # status stripped from ledger
    v = json.loads(r.stdout)
    assert v["status"] == "pass"


def test_assemble_pass_artifacts_object_shape(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "done", "files": ["leaf.v"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 0, r.stderr
    v = json.loads(r.stdout)
    # Envelope shape: artifacts is a list of {"path": …} objects (NOT flat strings).
    assert all(isinstance(a, dict) and "path" in a for a in v["artifacts"])
    paths = {a["path"] for a in v["artifacts"]}
    assert {
        "leaf.v",
        "top.v",
        "rtl-files.json",
        "constraint-annotations.json",
    } <= paths


def test_assemble_subset_rework_overlays_seeded(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "done", "files": ["leaf.v"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    assert _run(wd, man, top="top").returncode == 0
    # round 2: only 'leaf' re-dispatched, new file; --seeded carries 'topc' forward.
    (wd / "reaped-children.json").write_text(
        json.dumps(
            {"leaf": {"status": "done", "files": ["leaf_new.v"], "annotations": _ANN}}
        )
    )
    r = _run(wd, man, top="top", seeded=True)
    assert r.returncode == 0, r.stderr
    ledger = _read_state(wd)
    assert ledger["leaf"]["files"] == ["leaf_new.v"]  # re-dispatched child updated
    assert ledger["topc"]["files"] == ["top.v"]  # carried forward via --seeded


def test_assemble_manifest_shrink_evicts_the_dropped_child(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
        },
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    assert _run(wd, man, top="top").returncode == 0
    # seed a stale 'gone' into the on-disk ledger, then re-run with --seeded + shrunk roster.
    led = _read_state(wd)
    led["gone"] = {"files": ["gone.v"], "annotations": _ANN}
    _write_state(wd, led)
    (wd / "reaped-children.json").write_text(json.dumps({}))
    r = _run(wd, man, top="top", seeded=True)
    assert r.returncode == 0, r.stderr
    assert "gone" not in _read_state(wd)


def test_assemble_blocked_child_excluded(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "blocked", "reason": "iface incomplete"},
            "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    r = _run(wd, man, top="top")
    # post-gate fails on blocked-child precedence; the ledger has no 'leaf' entry.
    assert r.returncode == 1
    v = json.loads(r.stdout)
    assert v["status"] == "fail" and "blocked" in v["fail_reason"]
    assert set(_read_state(wd)) == {"topc"}


def test_assemble_fail_when_child_blocked_precedence(tmp_path):
    # alias-level coverage of P3: a passing coverage flips to fail when fresh has a blocked child.
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "blocked", "reason": "x"},
            "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    assert _run(wd, man, top="top").returncode == 1


def test_assemble_fail_zero_top_children(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={"leaf": {"status": "done", "files": ["leaf.v"], "annotations": _ANN}},
        children=[{"name": "leaf", "rtl_modules": ["leaf_m"]}],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 1
    assert "covered by 0 children" in json.loads(r.stdout)["fail_reason"]


def test_assemble_fail_two_top_children(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "a": {"status": "done", "files": ["a.v"], "annotations": _ANN},
            "b": {"status": "done", "files": ["b.v"], "annotations": _ANN},
        },
        children=[
            {"name": "a", "rtl_modules": ["top"]},
            {"name": "b", "rtl_modules": ["top"]},
        ],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 1
    assert "covered by 2 children" in json.loads(r.stdout)["fail_reason"]


def test_assemble_fail_top_child_not_pure(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "done", "files": ["leaf.v"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top", "wb_front"]},
        ],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 1
    assert "not pure" in json.loads(r.stdout)["fail_reason"]


def test_assemble_done_child_missing_files_build_error(tmp_path):
    # A done child MUST carry 'files' (child-task-contract). Missing it would silently drop
    # that child's RTL from rtl-files.json (Iron Rule #1) — a BUILD ERROR, distinct from a
    # gate fail: exit 1, message on STDERR, NO stdout verdict, ledger NOT written.
    wd, man = _setup(
        tmp_path,
        fresh={"topc": {"status": "done", "annotations": _ANN}},  # no 'files'
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 1
    assert "missing required 'files'" in r.stderr
    assert (
        r.stdout.strip() == ""
    )  # NO gate verdict on stdout (= build error, not gate fail)
    assert not (wd / "rtl-files.json").exists()  # no degraded sidecar written


def test_assemble_rejects_systemverilog_extension_build_error(tmp_path):
    # The kernel's downstream `rtl` selectors match *.v alone, so a .sv artifact silently
    # drops out of the derived dependency graph and its edits stop invalidating downstream
    # proofs. rtl-files.schema.json therefore constrains the extension, and write_ledger
    # validates BEFORE the first write — so the bad path never reaches disk for a later
    # --seeded run to inherit. Build error, not a gate fail: NO stdout verdict.
    wd, man = _setup(
        tmp_path,
        fresh={"topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN}},
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 1
    assert r.stdout.strip() == ""
    # the JSON pointer carries the child attribution a re-dispatch would need
    assert "rtl-files.json schema violation at $.topc.files[0]" in r.stderr
    assert not (wd / "rtl-files.json").exists()


def test_assemble_accepts_vh_header(tmp_path):
    # .vh headers are in scope for the same selectors; only .sv/.svh are the defect.
    wd, man = _setup(
        tmp_path,
        fresh={
            "topc": {
                "status": "done",
                "files": ["defs.vh", "top.v"],
                "annotations": _ANN,
            }
        },
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 0, r.stderr
    assert _read_state(wd)["topc"]["files"] == ["defs.vh", "top.v"]


def test_assemble_malformed_seeded_sidecar_build_error(tmp_path):
    # A malformed on-disk sidecar fed via --seeded -> load_ledger raises LedgerError ->
    # build error: exit 1, stderr naming the offending file and JSON pointer, NO stdout
    # verdict, and nothing is rewritten.
    wd, man = _setup(
        tmp_path,
        fresh={"topc": {"status": "done", "files": ["top.v"], "annotations": _ANN}},
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    # the seeded 'stale' record lacks the required 'files'.
    (wd / "rtl-files.json").write_text(json.dumps({"stale": {"bogus": 1}}))
    (wd / "constraint-annotations.json").write_text(json.dumps({"stale": _ANN}))
    r = _run(wd, man, top="top", seeded=True)
    assert r.returncode == 1
    assert r.stdout.strip() == ""  # build error -> no gate verdict on stdout
    # discriminating: the schema-violation wording + JSON pointer, not merely the path echoed
    # back by a read failure (which would also contain "rtl-files.json").
    assert "rtl-files.json schema violation at $.stale" in r.stderr
    assert "'files' is a required property" in r.stderr
    assert json.loads((wd / "rtl-files.json").read_text()) == {"stale": {"bogus": 1}}


def test_assemble_done_child_malformed_annotations_build_error(tmp_path):
    # A done child whose 'annotations' VALUE lacks 'sgdc'/'sdc' passes the key-presence check
    # and is caught by write_ledger's pre-write validate. Fail-loud: exit 1 + stderr, no
    # stdout verdict, and neither sidecar is created.
    wd, man = _setup(
        tmp_path,
        fresh={"topc": {"status": "done", "files": ["top.v"], "annotations": {}}},
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 1
    assert r.stdout.strip() == ""  # build error -> no gate verdict on stdout
    assert ("sgdc" in r.stderr) or (
        "sdc" in r.stderr
    )  # LedgerError names the missing sub-block
    assert not (wd / "rtl-files.json").is_file()  # validated before the first write


def test_assemble_seeded_blocked_keeps_stale_entry_but_gate_fails(tmp_path):
    # A child 'done' in a prior round (in the seeded ledger) that returns
    # 'blocked' in the new fresh is NOT evicted by the merge — its stale entry survives. This is
    # intentional (source never evicts a roster child present in seeded); the blocked child is
    # caught by post_verdict's fresh-based blocked-child precedence (status=fail) + SKILL.md 4.3's
    # mid-loop BLOCKED interception, NOT by ledger eviction. So the gate FAILS though the stale
    # entry remains (harmless — the stage is fail, so nothing promotes).
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "done", "files": ["leaf.v"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    assert _run(wd, man, top="top").returncode == 0  # round 1: both done
    # round 2: leaf now blocked; --seeded carries its stale round-1 entry.
    (wd / "reaped-children.json").write_text(
        json.dumps(
            {
                "leaf": {"status": "blocked", "reason": "iface regressed"},
                "topc": {"status": "done", "files": ["top.v"], "annotations": _ANN},
            }
        )
    )
    r = _run(wd, man, top="top", seeded=True)
    assert r.returncode == 1  # post_verdict fails on the blocked child in fresh
    assert "blocked" in json.loads(r.stdout)["fail_reason"]
    # the stale 'leaf' entry survives the merge (source-faithful; harmless — stage is fail)
    assert "leaf" in _read_state(wd)
