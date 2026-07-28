# tests/unit/test_rtl_assemble.py
"""rtl assemble verb — the four-script collapse (ledger build + filelist/README render +
post exit-gate) in one idempotent verb.

Layer 1: in-process pure render fns (render_filelist / render_readme).
Layer 2: the assemble CLI end-to-end — ledger build, the post-gate verdict on stdout, and
the build-error path (stderr + NO stdout verdict), which the main thread distinguishes.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"
sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
from rtl import assemble  # noqa: E402

_ANN = {"sgdc": {}, "sdc": {}}


# ── Layer 1: pure render fns (in-process) ─────────────────────────────────────
def test_render_filelist_aggregates():
    ledger = {
        "a": {"files": ["a.sv"], "incdirs": ["inc"], "annotations": _ANN},
        "b": {"files": ["b.sv"], "annotations": _ANN},
    }
    text = assemble.render_filelist(ledger)
    assert "+incdir+inc" in text
    assert "a.sv" in text and "b.sv" in text
    assert "//" not in text  # SpyGlass: '#' comments only


def test_render_filelist_dedups():
    ledger = {
        "a": {"files": ["pkg.sv", "a.sv"], "annotations": _ANN},
        "b": {"files": ["pkg.sv", "b.sv"], "annotations": _ANN},
    }
    assert assemble.render_filelist(ledger).count("pkg.sv") == 1


def test_render_readme_fallbacks():
    ledger = {"a": {"files": ["a.sv"], "annotations": {"sgdc": {}, "sdc": {}}}}
    text = assemble.render_readme(ledger)
    assert "single clock domain; no deep annotations needed." in text
    assert "set_false_path: none" in text


def test_render_readme_aggregated():
    ledger = {
        "leaf": {
            "files": ["s.sv"],
            "annotations": {
                "sgdc": {
                    "sync_cell": ["cdc_sync_2ff"],
                    "reset_synchronizer": [],
                    "set_case_analysis": [],
                    "quasi_static": [],
                },
                "sdc": {
                    "create_generated_clock": [{"module": "clkdiv", "pin": "clk_div2"}],
                    "set_multicycle_path": [],
                    "set_false_path": [],
                },
            },
        },
        "top": {
            "files": ["t.sv"],
            "annotations": {
                "sgdc": {
                    "sync_cell": [],
                    "reset_synchronizer": [],
                    "set_case_analysis": [{"port": "scan_en", "value": 0}],
                    "quasi_static": ["cfg_word"],
                },
                "sdc": {
                    "create_generated_clock": [],
                    "set_multicycle_path": [],
                    "set_false_path": [],
                },
            },
        },
    }
    text = assemble.render_readme(ledger)
    assert "sync_cell -name cdc_sync_2ff" in text
    assert "set_case_analysis 0 scan_en" in text
    assert "quasi_static -name cfg_word" in text
    assert "clkdiv.clk_div2" in text
    assert text.index("### SGDC") < text.index("### SDC")


# ── Layer 2: the assemble CLI end-to-end ──────────────────────────────────────
def _manifest(*children):
    return {"module": "top", "children": list(children)}


def _setup(tmp_path, *, fresh, children):
    wd = tmp_path / "runs" / "1"
    wd.mkdir(parents=True)
    (wd / "fresh_reports.json").write_text(json.dumps(fresh))
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
            "leaf": {"status": "done", "files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 0, r.stderr
    ledger = json.loads((wd / ".child_reports.json").read_text())
    assert set(ledger) == {"leaf", "topc"}
    assert "status" not in ledger["leaf"]  # status stripped from ledger
    assert (wd / "filelist.txt").is_file() and (wd / "README.md").is_file()
    v = json.loads(r.stdout)
    assert v["status"] == "pass"


def test_assemble_pass_artifacts_object_shape(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "done", "files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
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
        "leaf.sv",
        "top.sv",
        "filelist.txt",
        "README.md",
        ".child_reports.json",
    } <= paths


def test_assemble_subset_rework_overlays_seeded(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "done", "files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    assert _run(wd, man, top="top").returncode == 0
    # round 2: only 'leaf' re-dispatched, new file; --seeded carries 'topc' forward.
    (wd / "fresh_reports.json").write_text(
        json.dumps(
            {"leaf": {"status": "done", "files": ["leaf_new.sv"], "annotations": _ANN}}
        )
    )
    r = _run(wd, man, top="top", seeded=True)
    assert r.returncode == 0, r.stderr
    ledger = json.loads((wd / ".child_reports.json").read_text())
    assert ledger["leaf"]["files"] == ["leaf_new.sv"]  # re-dispatched child updated
    assert ledger["topc"]["files"] == ["top.sv"]  # carried forward via --seeded


def test_assemble_manifest_shrink_evicts_F2(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
        },
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    assert _run(wd, man, top="top").returncode == 0
    # seed a stale 'gone' into the on-disk ledger, then re-run with --seeded + shrunk roster.
    led = json.loads((wd / ".child_reports.json").read_text())
    led["gone"] = {"files": ["gone.sv"], "annotations": _ANN}
    (wd / ".child_reports.json").write_text(json.dumps(led))
    (wd / "fresh_reports.json").write_text(json.dumps({}))
    r = _run(wd, man, top="top", seeded=True)
    assert r.returncode == 0, r.stderr
    assert "gone" not in json.loads((wd / ".child_reports.json").read_text())


def test_assemble_blocked_child_excluded(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "blocked", "reason": "iface incomplete"},
            "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
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
    assert set(json.loads((wd / ".child_reports.json").read_text())) == {"topc"}


def test_assemble_fail_when_child_blocked_precedence(tmp_path):
    # alias-level coverage of P3: a passing coverage flips to fail when fresh has a blocked child.
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "blocked", "reason": "x"},
            "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
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
        fresh={"leaf": {"status": "done", "files": ["leaf.sv"], "annotations": _ANN}},
        children=[{"name": "leaf", "rtl_modules": ["leaf_m"]}],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 1
    assert "covered by 0 children" in json.loads(r.stdout)["fail_reason"]


def test_assemble_fail_two_top_children(tmp_path):
    wd, man = _setup(
        tmp_path,
        fresh={
            "a": {"status": "done", "files": ["a.sv"], "annotations": _ANN},
            "b": {"status": "done", "files": ["b.sv"], "annotations": _ANN},
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
            "leaf": {"status": "done", "files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
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
    # that child's RTL from filelist.txt (Iron Rule #1) — a BUILD ERROR, distinct from a
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
    assert not (wd / ".child_reports.json").exists()  # no degraded ledger written


def test_assemble_malformed_seeded_ledger_build_error(tmp_path):
    # A malformed on-disk ledger fed via --seeded (a record missing 'annotations') ->
    # load_ledger raises LedgerError -> build error: exit 1, stderr, NO stdout verdict, and
    # the render fns are never reached (no degraded filelist/README). This carries the
    # source's test_fail_loud_on_malformed_ledger_F8 (filelist + readme) end-to-end through
    # the verb, now routed via the seeded read (render fns can no longer see a raw ledger).
    wd, man = _setup(
        tmp_path,
        fresh={"topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN}},
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    # malformed seeded ledger: the 'stale' record is missing the required 'annotations'.
    (wd / ".child_reports.json").write_text(json.dumps({"stale": {"files": ["x.sv"]}}))
    r = _run(wd, man, top="top", seeded=True)
    assert r.returncode == 1
    assert r.stdout.strip() == ""  # build error -> no gate verdict on stdout
    assert "annotations" in r.stderr  # LedgerError names the missing sub-block
    assert not (wd / "filelist.txt").exists()  # no degraded render output


def test_assemble_done_child_malformed_annotations_build_error(tmp_path):
    # A done child whose 'annotations' VALUE lacks 'sgdc'/'sdc' passes the key-presence check,
    # so the produced ledger is written THEN rejected by the load_ledger re-validate
    # (write-then-validate — source-faithful). Fail-loud: exit 1 + stderr, no stdout verdict,
    # no degraded RENDER output. The .child_reports.json is left on disk (source-faithful,
    # harmless), so this deliberately does NOT assert its absence (C3).
    wd, man = _setup(
        tmp_path,
        fresh={"topc": {"status": "done", "files": ["top.sv"], "annotations": {}}},
        children=[{"name": "topc", "rtl_modules": ["top"]}],
    )
    r = _run(wd, man, top="top")
    assert r.returncode == 1
    assert r.stdout.strip() == ""  # build error -> no gate verdict on stdout
    assert ("sgdc" in r.stderr) or (
        "sdc" in r.stderr
    )  # LedgerError names the missing sub-block
    assert not (wd / "filelist.txt").exists()  # no degraded render output


def test_assemble_seeded_blocked_keeps_stale_entry_but_gate_fails(tmp_path):
    # Source-faithful (C2): a child 'done' in a prior round (in the seeded ledger) that returns
    # 'blocked' in the new fresh is NOT evicted by the merge — its stale entry survives. This is
    # intentional (source never evicts a roster child present in seeded); the blocked child is
    # caught by post_verdict's fresh-based blocked-child precedence (status=fail) + SKILL.md 4.3's
    # mid-loop BLOCKED interception, NOT by ledger eviction. So the gate FAILS though the stale
    # entry remains (harmless — the stage is fail, so nothing promotes).
    wd, man = _setup(
        tmp_path,
        fresh={
            "leaf": {"status": "done", "files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
        },
        children=[
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
    )
    assert _run(wd, man, top="top").returncode == 0  # round 1: both done
    # round 2: leaf now blocked; --seeded carries its stale round-1 entry.
    (wd / "fresh_reports.json").write_text(
        json.dumps(
            {
                "leaf": {"status": "blocked", "reason": "iface regressed"},
                "topc": {"status": "done", "files": ["top.sv"], "annotations": _ANN},
            }
        )
    )
    r = _run(wd, man, top="top", seeded=True)
    assert r.returncode == 1  # post_verdict fails on the blocked child in fresh
    assert "blocked" in json.loads(r.stdout)["fail_reason"]
    # the stale 'leaf' entry survives the merge (source-faithful; harmless — stage is fail)
    assert "leaf" in json.loads((wd / ".child_reports.json").read_text())
