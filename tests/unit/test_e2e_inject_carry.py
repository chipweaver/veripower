"""End-to-end validation (Task 17, spec §10 #9): the kernel CLI drives real
dispatch -> execute -> reap -> promote rounds under inject+carry for (1) the
richest AUTHOR (rtl-design, which self-carries its own prior round into a
fresh workdir) and (2) a TRANSFORMER spanning four upstream stages
(power-analysis), plus (3) the "relocation invariance" behavioral proof (spec
§10 #5 — the REAL criterion, not just token-absence): move the whole canonical
tree wholesale and the consumer still re-anchors, because it re-reads
`inputs.json` every round instead of trusting a baked cross-stage path.

Model: test_kernel_cli.py's `_run_json`/`_dispatch_write_reap` subprocess idiom
(same per-stage minimal schema-valid `stage_specific`/output-file sets), scoped
here to only the stages these three tests need (specification, simulation-plan,
rtl-design, synthesis, simulation, power-analysis).
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = str(ROOT / "framework" / "scripts" / "kernel.py")
SYNTH_MAIN = ROOT / "skills" / "synthesis" / "scripts" / "synthesis" / "__main__.py"
POWER_MAIN = ROOT / "skills" / "power-analysis" / "scripts" / "power" / "__main__.py"


def _now_iso() -> str:
    """Second-resolution UTC stamp, mirroring the skill finalizers' _now_iso()
    (test_kernel_cli.py's helper) — so a result.json written mid-test passes the
    reap temporal-integrity check the same way a real freshly-finalized envelope
    does."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(tree_root, *args):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        cwd=str(tree_root),
    )


def _run_json(tree_root, *args):
    r = _run(tree_root, *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _write_file(tree_root, module, rel, content):
    p = tree_root / "asic" / module / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# Minimal pass-valid stage_specific per stage used here — exactly the per-stage
# schema's status=pass conditional requirements (skills/<stage>/references/
# result.schema.json), so reap-time schema validation genuinely passes.
_STAGE_SPECIFIC = {
    "specification": {"top_module": "top", "ppa_targets": []},
    "simulation-plan": {},
    "rtl-design": {},
    "synthesis": {"ppa_actual": []},
    "simulation": {},
    "power-analysis": {
        "saif_artifacts": [],
        "compile_info": {"vcs_version": "test"},
        "failures": [],
        "ppa_actual": [],
        "violations": [],
        "power_by_corner": [],
    },
}

# Minimal declared-output set per stage: exactly the files downstream rules'
# own `inputs` selectors reference (per rules.RULES).
_STAGE_FILES = {
    "specification": {
        "design.md": "design v1",
        "manifest.json": "{}",
        "ppa.json": "{}",
        "clocks.json": "[]",
        "features.json": "[]",
        "timing-scenarios.json": "[]",
        "check-hints/child_a.json": "[]",
        "top-io.json": "[]",
        "interconnects.json": "[]",
        "child_a.md": "child a design",  # a real per-child doc (N>=1), distinct
        # from design.md, so the "children" selector has a genuine match of its own
        "constraints/top.sdc": "# sdc",
        "constraints/top.sgdc": "# sgdc",
    },
    "simulation-plan": {
        "verification-plan.md": "plan v1",
        "scaffold-specification.json": "{}",
    },
    "rtl-design": {
        "top.v": "module top; endmodule",
        "rtl-files.json": '{"child_a": {"files": ["top.v"]}}',
        "constraint-annotations.json": "{}",
    },
    "synthesis": {
        "out/top_syn.v": "module top; endmodule",
        "out/top_syn.sdc": "# sdc",
        "out/top_syn.sdf": "# sdf",
        "reports/qor.rpt": "qor",
    },
    "simulation": {
        "case-results-summary.md": "all pass",
        "env.sh": "#!/bin/sh",
        "filelist.f": "-f rtl_filelist.f",
        "rtl_filelist.f": "top.v",
        "tb/uvm/dummy.sv": "// tb",
    },
    "power-analysis": {
        "reports_ptpx/run1/power_hier.rpt": "power ok",
    },
}


def _dispatch_write_reap(tree_root, module, rule, files, *, objective="delivery"):
    """dispatch `rule`, write `files` (workdir-relative path -> content) + a
    passing schema-valid result.json declaring them as artifacts, then reap.
    Returns the reap JSON."""
    d = _run_json(
        tree_root,
        "dispatch",
        "--module",
        module,
        "--rule",
        rule,
        "--objective",
        objective,
    )
    assert d["ok"] is True, d
    workdir = d["workdir"]
    for rel, content in files.items():
        _write_file(tree_root, module, f"{workdir}/{rel}", content)
    result = {
        "schema_version": 1,
        "stage": rule,
        "module": module,
        "produced_at": _now_iso(),
        "status": "pass",
        "artifacts": [{"path": p} for p in files],
        "stage_specific": _STAGE_SPECIFIC[rule],
    }
    _write_file(tree_root, module, f"{workdir}/result.json", json.dumps(result))
    return _run_json(
        tree_root, "reap", "--module", module, "--rule", rule, "--run", str(d["run"])
    )


def test_rtl_author_dispatch_reap_promote_green(tmp_path):
    module = "m"
    # 1. seed upstream canonical (specification products) + brainstorm
    _write_file(tmp_path, module, "brainstorm.md", "b1")
    spec = _dispatch_write_reap(
        tmp_path, module, "specification", _STAGE_FILES["specification"]
    )
    assert spec["ok"] is True and spec["verdict"] == "pass", spec

    # 2. dispatch rtl-design -> inputs.json's design/manifest/children all
    # resolve to the SAME producer (specification) stage root, absolute.
    d1 = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        module,
        "--rule",
        "rtl-design",
        "--objective",
        "delivery",
    )
    assert d1["ok"] is True, d1
    wd1 = tmp_path / "asic" / module / d1["workdir"]
    table = json.loads((wd1 / "inputs.json").read_text())
    spec_root = str((tmp_path / "asic" / module / "Design" / "specification").resolve())
    assert table["design"] == spec_root
    assert table["manifest"] == spec_root
    assert table["children"] == spec_root

    # 3. write a schema-valid rtl result.json in the workdir, reap -> verdict
    # pass, promote
    for rel, content in _STAGE_FILES["rtl-design"].items():
        _write_file(tmp_path, module, f"{d1['workdir']}/{rel}", content)
    result1 = {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": module,
        "produced_at": _now_iso(),
        "status": "pass",
        "artifacts": [{"path": p} for p in _STAGE_FILES["rtl-design"]],
        "stage_specific": _STAGE_SPECIFIC["rtl-design"],
    }
    _write_file(tmp_path, module, f"{d1['workdir']}/result.json", json.dumps(result1))
    r1 = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "rtl-design",
        "--run",
        str(d1["run"]),
    )
    assert r1 == {"ok": True, "rule": "rtl-design", "run": d1["run"], "verdict": "pass"}
    canonical = tmp_path / "asic" / module / "Design" / "rtl-design"
    assert (canonical / "top.v").read_text() == _STAGE_FILES["rtl-design"]["top.v"]

    # 4. re-dispatch rtl-design -> the previous *.v and both sidecars were
    # CARRIED into the new workdir (carry_self), not re-authored from scratch.
    d2 = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        module,
        "--rule",
        "rtl-design",
        "--objective",
        "delivery",
    )
    assert d2["ok"] is True and d2["run"] == d1["run"] + 1
    wd2 = tmp_path / "asic" / module / d2["workdir"]
    assert (wd2 / "top.v").read_text() == _STAGE_FILES["rtl-design"]["top.v"]
    assert (wd2 / "rtl-files.json").read_text() == _STAGE_FILES["rtl-design"][
        "rtl-files.json"
    ]
    assert (wd2 / "constraint-annotations.json").read_text() == _STAGE_FILES[
        "rtl-design"
    ]["constraint-annotations.json"]


def test_power_transformer_filelist_across_sim_and_synth(tmp_path):
    module = "m"
    _write_file(tmp_path, module, "brainstorm.md", "b1")
    # A scaffold-specification.json with real content — the deployed
    # emit_power_tests.py (shelled out to by the real power bootstrap below)
    # enforces the sim-plan -> power cross-stage contract (power_scenarios[].
    # sequence_ref must resolve to sequences[].name).
    simplan_files = {
        "verification-plan.md": "plan v1",
        "scaffold-specification.json": json.dumps(
            {
                "sequences": [{"name": "idle_seq", "agent": "cpu"}],
                "power_scenarios": [
                    {
                        "id": "S1",
                        "sequence_ref": "idle_seq",
                        "scenario": "idle",
                        "duration_cycles": 1000,
                    }
                ],
            }
        ),
    }
    # seed synthesis (netlist) + simulation (tb_env) + simulation-plan
    # (scaffold) + spec (ppa) canonical, each through a real dispatch+reap
    for rule, files in (
        ("specification", _STAGE_FILES["specification"]),
        ("simulation-plan", simplan_files),
        ("rtl-design", _STAGE_FILES["rtl-design"]),
        ("synthesis", _STAGE_FILES["synthesis"]),
        ("simulation", _STAGE_FILES["simulation"]),
    ):
        outcome = _dispatch_write_reap(tmp_path, module, rule, files)
        assert outcome["ok"] is True and outcome["verdict"] == "pass", outcome

    # dispatch power-analysis -> inputs.json spans all four keys as absolute
    # stage roots
    d = _run_json(
        tmp_path,
        "dispatch",
        "--module",
        module,
        "--rule",
        "power-analysis",
        "--objective",
        "delivery",
    )
    assert d["ok"] is True, d
    wd = tmp_path / "asic" / module / d["workdir"]
    table = json.loads((wd / "inputs.json").read_text())
    base = str((tmp_path / "asic" / module).resolve())
    assert table["netlist"] == base + "/Design/synthesis"
    assert table["tb_env"] == base + "/Verification/simulation"
    assert table["scaffold"] == base + "/Verification/simulation-plan"
    assert table["ppa"] == base + "/Design/specification"
    for key in ("netlist", "tb_env", "scaffold", "ppa"):
        assert Path(table[key]).is_absolute()

    # EXECUTE: the real power bootstrap script, reading the kernel-injected
    # inputs.json exactly as a real task dispatch would -> env.sh's *_DIR
    # substitutions are absolute stage roots, no relpath climb.
    br = subprocess.run(
        [
            sys.executable,
            str(POWER_MAIN),
            "bootstrap",
            "--module",
            module,
            "--workdir",
            str(wd),
            "--top",
            "top",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert br.returncode == 0, br.stderr
    env_sh = (wd / "env.sh").read_text()
    assert f'export NETLIST="{table["netlist"]}/out/' in env_sh
    assert f'export TB_DIR="{table["tb_env"]}"' in env_sh
    assert "/../" not in env_sh  # no relpath climb regardless of workdir depth

    # reap -> promote green
    for rel, content in _STAGE_FILES["power-analysis"].items():
        _write_file(tmp_path, module, f"{d['workdir']}/{rel}", content)
    result = {
        "schema_version": 1,
        "stage": "power-analysis",
        "module": module,
        "produced_at": _now_iso(),
        "status": "pass",
        "artifacts": [{"path": p} for p in _STAGE_FILES["power-analysis"]],
        "stage_specific": _STAGE_SPECIFIC["power-analysis"],
    }
    _write_file(tmp_path, module, f"{d['workdir']}/result.json", json.dumps(result))
    r = _run_json(
        tmp_path,
        "reap",
        "--module",
        module,
        "--rule",
        "power-analysis",
        "--run",
        str(d["run"]),
    )
    assert r == {
        "ok": True,
        "rule": "power-analysis",
        "run": d["run"],
        "verdict": "pass",
    }
    canonical = tmp_path / "asic" / module / "Verification" / "power-analysis"
    assert (canonical / "reports_ptpx" / "run1" / "power_hier.rpt").is_file()


def test_relocation_invariance_consumer_reanchors(tmp_path):
    # spec §10 #5 (the REAL criterion — not "no relpath token"): move canonical
    # wholesale and the consumer still resolves, because it re-reads
    # inputs.json each round instead of trusting a baked cross-stage path.
    module = "m"
    tree_a = tmp_path / "a"
    tree_a.mkdir()
    _write_file(tree_a, module, "brainstorm.md", "b1")
    for rule in ("specification", "rtl-design"):
        outcome = _dispatch_write_reap(tree_a, module, rule, _STAGE_FILES[rule])
        assert outcome["ok"] is True and outcome["verdict"] == "pass", outcome

    # Dispatch synthesis under tree A -> rtl_load.tcl points into A.
    d_a = _run_json(
        tree_a,
        "dispatch",
        "--module",
        module,
        "--rule",
        "synthesis",
        "--objective",
        "delivery",
    )
    assert d_a["ok"] is True, d_a
    wd_a = tree_a / "asic" / module / d_a["workdir"]
    br_a = subprocess.run(
        [
            sys.executable,
            str(SYNTH_MAIN),
            "bootstrap",
            "--workdir",
            str(wd_a),
            "--top",
            "top",
        ],
        cwd=str(tree_a),
        capture_output=True,
        text=True,
    )
    assert br_a.returncode == 0, br_a.stderr
    tcl_a = (wd_a / "scripts" / "rtl_load.tcl").read_text()
    rtl_root_a = str((tree_a / "asic" / module / "Design" / "rtl-design").resolve())
    assert rtl_root_a in tcl_a

    # reap synthesis run 1 in A (so it is no longer in-flight) -> promote
    for rel, content in _STAGE_FILES["synthesis"].items():
        _write_file(tree_a, module, f"{d_a['workdir']}/{rel}", content)
    result = {
        "schema_version": 1,
        "stage": "synthesis",
        "module": module,
        "produced_at": _now_iso(),
        "status": "pass",
        "artifacts": [{"path": p} for p in _STAGE_FILES["synthesis"]],
        "stage_specific": _STAGE_SPECIFIC["synthesis"],
    }
    _write_file(tree_a, module, f"{d_a['workdir']}/result.json", json.dumps(result))
    reap_a = _run_json(
        tree_a,
        "reap",
        "--module",
        module,
        "--rule",
        "synthesis",
        "--run",
        str(d_a["run"]),
    )
    assert reap_a["ok"] is True and reap_a["verdict"] == "pass", reap_a

    # Copy the WHOLE asic tree (events.jsonl + canonical products) to a second
    # location B.
    tree_b = tmp_path / "b"
    shutil.copytree(tree_a, tree_b)

    # Re-dispatch synthesis THERE -> a fresh run 2 whose inject_inputs
    # recomputes the rtl stage root against tree B's own cwd.
    d_b = _run_json(
        tree_b,
        "dispatch",
        "--module",
        module,
        "--rule",
        "synthesis",
        "--objective",
        "delivery",
    )
    assert d_b["ok"] is True, d_b
    assert d_b["run"] == d_a["run"] + 1
    wd_b = tree_b / "asic" / module / d_b["workdir"]
    br_b = subprocess.run(
        [
            sys.executable,
            str(SYNTH_MAIN),
            "bootstrap",
            "--workdir",
            str(wd_b),
            "--top",
            "top",
        ],
        cwd=str(tree_b),
        capture_output=True,
        text=True,
    )
    assert br_b.returncode == 0, br_b.stderr

    # rtl_load.tcl now points into B (the new absolute rtl root), NEVER the
    # stale A path.
    tcl_b = (wd_b / "scripts" / "rtl_load.tcl").read_text()
    assert str(tree_b) in tcl_b and str(tree_a) not in tcl_b
