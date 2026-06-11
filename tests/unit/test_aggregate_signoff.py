# tests/unit/test_aggregate_signoff.py
"""Tests for skills/frontend-signoff/scripts/aggregate_signoff.py.

frontend-signoff is a pure aggregator: it reads the 6 upstream canonical
result.json envelopes + fixed evidence paths (JSON/filesystem only, no markdown
parsing) and writes checklist.md + traceability.md skeleton + a script-authored
result.json. The script owns the pass/fail gate; the agent composes only the
feature->evidence matrix afterward.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/frontend-signoff/scripts/aggregate_signoff.py"
sys.path.insert(0, str(ROOT / "skills/frontend-signoff/scripts"))
import aggregate_signoff as ag  # noqa: E402

# ── the 6 upstream canonical envelopes (stage, relative path under asic_root) ──
_UPSTREAM = {
    "power-analysis": "Verification/power-analysis/result.json",
    "timing-analysis": "Design/timing-analysis/result.json",
    "simulation": "Verification/simulation/result.json",
    "synthesis": "Design/synthesis/result.json",
    "lint-cdc": "Design/lint-cdc/result.json",
    "specification": "Design/specification/result.json",
}


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _passing_tree(tmp_path: Path) -> Path:
    """Build a fully-passing asic/<M>/ tree; return asic_root."""
    asic_root = tmp_path / "asic" / "M"
    for stage, rel in _UPSTREAM.items():
        _write_json(asic_root / rel, {"status": "pass", "stage_specific": {}})
    return asic_root


def test_read_envelopes_all_pass_no_failures(tmp_path):
    asic_root = _passing_tree(tmp_path)
    by_stage, failures = ag.read_envelopes(asic_root)
    assert failures == []
    assert set(by_stage) == set(_UPSTREAM)
    assert by_stage["synthesis"]["status"] == "pass"


def test_read_envelopes_missing_one(tmp_path):
    asic_root = _passing_tree(tmp_path)
    (asic_root / _UPSTREAM["synthesis"]).unlink()
    _, failures = ag.read_envelopes(asic_root)
    assert any("synthesis" in f and "missing" in f for f in failures)


def test_read_envelopes_not_pass(tmp_path):
    asic_root = _passing_tree(tmp_path)
    _write_json(
        asic_root / _UPSTREAM["lint-cdc"], {"status": "fail", "stage_specific": {}}
    )
    _, failures = ag.read_envelopes(asic_root)
    assert any("lint-cdc" in f and "not pass" in f for f in failures)


def test_read_envelopes_unparseable(tmp_path):
    asic_root = _passing_tree(tmp_path)
    (asic_root / _UPSTREAM["timing-analysis"]).write_text("{not json", encoding="utf-8")
    _, failures = ag.read_envelopes(asic_root)
    assert any("timing-analysis" in f and "unparseable" in f for f in failures)


def test_derive_asic_root_from_workdir():
    workdir = Path("/x/asic/M/frontend-signoff/runs/3")
    assert ag.derive_asic_root(workdir) == Path("/x/asic/M")


# ── evidence resolution (concrete paths + reachability) ──────────────────────
_EVIDENCE = [
    "Design/specification/design.md",
    "Design/lint-cdc/lint-report.txt",
    "Design/lint-cdc/cdc-report.txt",
    "Verification/simulation/case-results-summary.md",
    "Design/timing-analysis/timing-report.txt",
    "Design/synthesis/reports/qor.rpt",
]


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def _evidence_tree(asic_root: Path, *, power_dirs=("run0",)) -> None:
    """Create all fixed evidence files + power_hier.rpt under each given ptpx dir."""
    for rel in _EVIDENCE:
        _touch(asic_root / rel)
    for d in power_dirs:
        _touch(
            asic_root
            / "Verification/power-analysis/reports_ptpx"
            / d
            / "power_hier.rpt"
        )


def test_resolve_evidence_all_reachable(tmp_path):
    asic_root = _passing_tree(tmp_path)
    _evidence_tree(asic_root)
    records, failures = ag.resolve_evidence(asic_root)
    assert failures == []
    paths = {r["path"] for r in records}
    assert "Design/synthesis/reports/qor.rpt" in paths
    # the globbed power report is resolved to its CONCRETE path, on_disk True
    pwr = next(r for r in records if "power_hier.rpt" in r["path"])
    assert pwr["on_disk"] is True
    assert pwr["path"] == "Verification/power-analysis/reports_ptpx/run0/power_hier.rpt"


def test_resolve_evidence_one_missing(tmp_path):
    asic_root = _passing_tree(tmp_path)
    _evidence_tree(asic_root)
    (asic_root / "Design/synthesis/reports/qor.rpt").unlink()
    _, failures = ag.resolve_evidence(asic_root)
    assert any("qor.rpt" in f for f in failures)


def test_resolve_evidence_power_glob_zero(tmp_path):
    asic_root = _passing_tree(tmp_path)
    _evidence_tree(asic_root, power_dirs=())  # no power_hier.rpt
    _, failures = ag.resolve_evidence(asic_root)
    assert any("power_hier.rpt" in f and "unreachable" in f for f in failures)


def test_resolve_evidence_power_glob_conflict(tmp_path):
    asic_root = _passing_tree(tmp_path)
    _evidence_tree(asic_root, power_dirs=("run0", "run1"))  # two matches
    _, failures = ag.resolve_evidence(asic_root)
    assert any("power_hier.rpt" in f and "conflict" in f for f in failures)


# ── traceability inputs (existence/readability only — NOT parsed) ─────────────
def _spec_inputs(asic_root: Path, *, children=("c0",)) -> None:
    spec = asic_root / "Design/specification"
    _touch(spec / "design.md")
    manifest = {
        "module": "M",
        "children": [{"name": c, "doc": f"{c}.md"} for c in children],
    }
    (spec / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for c in children:
        _touch(spec / f"{c}.md")


def test_check_traceability_inputs_ok(tmp_path):
    asic_root = _passing_tree(tmp_path)
    _spec_inputs(asic_root)
    assert ag.check_traceability_inputs(asic_root) == []


def test_check_traceability_inputs_manifest_missing(tmp_path):
    asic_root = _passing_tree(tmp_path)
    _spec_inputs(asic_root)
    (asic_root / "Design/specification/manifest.json").unlink()
    failures = ag.check_traceability_inputs(asic_root)
    assert any("manifest.json" in f for f in failures)


def test_check_traceability_inputs_child_missing(tmp_path):
    asic_root = _passing_tree(tmp_path)
    _spec_inputs(asic_root, children=("c0", "c1"))
    (asic_root / "Design/specification/c1.md").unlink()
    failures = ag.check_traceability_inputs(asic_root)
    assert any("c1.md" in f for f in failures)


# ── headline PPA (best-effort, non-gating) ───────────────────────────────────
def test_extract_ppa_pulls_values(tmp_path):
    by_stage = {
        "synthesis": {
            "stage_specific": {"ppa_actual": [{"dim": "area_um2", "value": 65018.2}]}
        },
        "timing-analysis": {
            "stage_specific": {
                "timing": {
                    "setup": {"worst_slack_ns": 0.95},
                    "hold": {"worst_slack_ns": 0.12},
                }
            }
        },
        "power-analysis": {
            "stage_specific": {
                "ppa_actual": [
                    {"dim": "power_mw", "value": 12.3, "scenario_id": "s0"},
                    {"dim": "power_mw", "value": 14.1, "scenario_id": "s1"},
                ],
                "compile_info": {"vcs_version": "U-2023.03"},
            }
        },
    }
    ppa = ag.extract_ppa(by_stage)
    assert ppa["area_um2"] == 65018.2
    assert ppa["setup_wns_ns"] == 0.95
    assert ppa["power_mw"] == 14.1  # worst-case (max) across scenarios
    assert ppa["vcs_version"] == "U-2023.03"


def test_extract_ppa_tolerates_absence(tmp_path):
    ppa = ag.extract_ppa(
        {"synthesis": None, "timing-analysis": {}, "power-analysis": {}}
    )
    assert ppa["area_um2"] is None and ppa["setup_wns_ns"] is None
    assert ppa["power_mw"] is None and ppa["vcs_version"] is None


# ── rendering + envelope assembly ────────────────────────────────────────────
_EVIDENCE_RECORDS = [
    {"path": "Design/synthesis/reports/qor.rpt", "on_disk": True},
    {"path": "Design/timing-analysis/timing-report.txt", "on_disk": True},
    {
        "path": "Verification/power-analysis/reports_ptpx/run0/power_hier.rpt",
        "on_disk": True,
    },
]


def test_render_checklist_has_stages_and_verdict():
    by_stage = {s: {"status": "pass", "stage_specific": {}} for s in _UPSTREAM}
    ppa = ag.extract_ppa(by_stage)
    md = ag.render_checklist(
        "M", by_stage, ppa, _EVIDENCE_RECORDS, status="pass", failures=[]
    )
    assert "synthesis" in md and "specification" in md
    assert "pass" in md.lower()


def test_render_checklist_lists_failures():
    by_stage = {s: {"status": "pass", "stage_specific": {}} for s in _UPSTREAM}
    md = ag.render_checklist(
        "M",
        by_stage,
        ag.extract_ppa(by_stage),
        _EVIDENCE_RECORDS,
        status="fail",
        failures=["lint-cdc: not pass (status='fail')"],
    )
    assert "lint-cdc: not pass" in md


def test_render_checklist_lists_evidence_paths():
    by_stage = {s: {"status": "pass", "stage_specific": {}} for s in _UPSTREAM}
    md = ag.render_checklist(
        "M",
        by_stage,
        ag.extract_ppa(by_stage),
        _EVIDENCE_RECORDS,
        status="pass",
        failures=[],
    )
    # checklist.md carries the auditable evidence-path list
    assert "qor.rpt" in md
    assert "reports_ptpx/run0/power_hier.rpt" in md


def test_render_traceability_skeleton_has_agent_placeholders():
    md = ag.render_traceability_skeleton("M", ag.extract_ppa({}), _EVIDENCE_RECORDS)
    assert "Feature" in md and "evidence" in md.lower()
    assert "agent" in md.lower()  # explicit hand-off marker for the matrix/summary


def test_render_traceability_has_report_index():
    md = ag.render_traceability_skeleton("M", ag.extract_ppa({}), _EVIDENCE_RECORDS)
    # traceability skeleton = report index (which reports on disk + paths)
    assert "Report index" in md
    assert "timing-report.txt" in md


def test_build_envelope_required_fields_and_no_self_list():
    env = ag.build_envelope(
        "M",
        status="pass",
        fail_reason=None,
        artifacts=[{"path": "checklist.md"}, {"path": "traceability.md"}],
    )
    for key in (
        "stage",
        "module",
        "produced_at",
        "status",
        "artifacts",
        "stage_specific",
        "schema_version",
    ):
        assert key in env
    assert env["stage"] == "frontend-signoff" and env["schema_version"] == 1
    assert env["stage_specific"] == {}
    assert all(a["path"] != "result.json" for a in env["artifacts"])


def test_build_envelope_fail_has_reason():
    env = ag.build_envelope("M", status="fail", fail_reason="x: not pass", artifacts=[])
    assert env["status"] == "fail"
    assert env["stage_specific"]["fail_reason"] == "x: not pass"


# ── end-to-end via subprocess (real exit codes) + envelope schema validity ───
from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"


def _validate_envelope(obj: dict) -> None:
    env_schema = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (ROOT / "skills/frontend-signoff/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        _ENVELOPE_URI, Resource.from_contents(env_schema)
    )
    Draft202012Validator(stage_schema, registry=registry).validate(obj)


def _full_tree(tmp_path: Path, children=("c0",)) -> Path:
    """Build a complete passing tree; return the frontend-signoff run workdir."""
    asic_root = _passing_tree(tmp_path)
    _evidence_tree(asic_root)
    _spec_inputs(asic_root, children=children)
    workdir = asic_root / "frontend-signoff" / "runs" / "1"
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def _run(workdir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--workdir", str(workdir), "--module", "M"],
        capture_output=True,
        text=True,
    )


def test_e2e_all_pass(tmp_path):
    workdir = _full_tree(tmp_path)
    cp = _run(workdir)
    assert cp.returncode == 0, cp.stderr
    rj = json.loads((workdir / "result.json").read_text())
    assert rj["status"] == "pass"
    assert (workdir / "checklist.md").is_file()
    assert (workdir / "traceability.md").is_file()
    # the produced docs carry the auditable evidence/report paths
    assert "qor.rpt" in (workdir / "checklist.md").read_text()
    assert "Report index" in (workdir / "traceability.md").read_text()
    paths = {a["path"] for a in rj["artifacts"]}
    assert paths == {"checklist.md", "traceability.md"}
    assert "result.json" not in paths
    _validate_envelope(rj)


def test_e2e_envelope_not_pass(tmp_path):
    workdir = _full_tree(tmp_path)
    asic_root = workdir.parents[2]
    _write_json(
        asic_root / _UPSTREAM["synthesis"], {"status": "fail", "stage_specific": {}}
    )
    cp = _run(workdir)
    assert cp.returncode == 0, cp.stderr
    rj = json.loads((workdir / "result.json").read_text())
    assert rj["status"] == "fail"
    assert "synthesis" in rj["stage_specific"]["fail_reason"]
    _validate_envelope(rj)


def test_e2e_envelope_missing(tmp_path):
    workdir = _full_tree(tmp_path)
    (workdir.parents[2] / _UPSTREAM["simulation"]).unlink()
    cp = _run(workdir)
    assert cp.returncode == 0
    rj = json.loads((workdir / "result.json").read_text())
    assert (
        rj["status"] == "fail" and "simulation" in rj["stage_specific"]["fail_reason"]
    )


def test_e2e_evidence_unreachable(tmp_path):
    workdir = _full_tree(tmp_path)
    (workdir.parents[2] / "Design/timing-analysis/timing-report.txt").unlink()
    cp = _run(workdir)
    assert cp.returncode == 0
    rj = json.loads((workdir / "result.json").read_text())
    assert (
        rj["status"] == "fail"
        and "timing-report.txt" in rj["stage_specific"]["fail_reason"]
    )


def test_e2e_spec_pass_but_manifest_missing(tmp_path):
    workdir = _full_tree(tmp_path)
    (workdir.parents[2] / "Design/specification/manifest.json").unlink()
    cp = _run(workdir)
    assert cp.returncode == 0
    rj = json.loads((workdir / "result.json").read_text())
    assert (
        rj["status"] == "fail"
        and "manifest.json" in rj["stage_specific"]["fail_reason"]
    )


def test_e2e_blocked_when_cannot_operate(tmp_path):
    # workdir does not exist at parents[2] depth -> derive_asic_root points nowhere
    # writable; the doc/result writes raise -> exit != 0, no valid result.json.
    workdir = tmp_path / "asic" / "M" / "frontend-signoff" / "runs" / "1"
    # deliberately do NOT create workdir -> write_text raises
    cp = _run(workdir)
    assert cp.returncode != 0
    assert not (workdir / "result.json").exists()
