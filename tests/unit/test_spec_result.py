# tests/unit/test_spec_result.py
import json
import shutil
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "specification" / "scripts"))
from spec import constraints, result  # noqa: E402

_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"
_FIX = Path(__file__).resolve().parent / "fixtures" / "specification-golden"
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"

_ROWS = [
    {
        "id": "R-001",
        "verbatim": "done pulses one cycle after start",
        "judge": "simulation",
    },
    {
        "id": "R-002",
        "verbatim": "area at most 70000 um2",
        "judge": "synthesis",
        "target": {"dim": "area_um2", "op": "<=", "value": 70000.0},
    },
]


def _spec_workdir(tmp_path, rows=None):
    """A workdir derive_constraints() can run over (valid clocks.json + top-io.json) plus
    the finalize inputs (manifest / ledger / per-child md / hints / spec-review)."""
    wd = tmp_path
    (wd / "design.md").write_text("# dut_top Design\n\nNarrative only.\n")
    (wd / "top-io.json").write_text(
        json.dumps(
            [
                {
                    "name": "i_clk",
                    "direction": "input",
                    "width": 1,
                    "clock_domain": "i_clk",
                    "interface_group": "clk",
                    "role": "clock",
                }
            ]
        )
    )
    (wd / "clocks.json").write_text(
        json.dumps(
            [
                {
                    "name": "i_clk",
                    "period_ns": 10.0,
                    "relationship": "primary",
                    "role": "primary clock",
                }
            ]
        )
    )
    (wd / "manifest.json").write_text(
        json.dumps(
            {
                "module": "dut_top",
                "children": [
                    {
                        "name": "dut_top",
                        "doc": "children/dut_top.md",
                        "rtl_modules": ["dut_top"],
                    }
                ],
            }
        )
    )
    (wd / "children").mkdir(exist_ok=True)
    (wd / "children" / "dut_top.md").write_text(
        "---\nports: []\nclocks: []\n---\n\n# child\n"
    )
    (wd / "requirements.json").write_text(json.dumps(_ROWS if rows is None else rows))
    (wd / "interconnects.json").write_text(json.dumps([]))
    (wd / "check-hints").mkdir(exist_ok=True)
    (wd / "check-hints" / "dut_top.json").write_text(
        json.dumps(
            [
                {
                    "check_id": "CHK-00",
                    "requirements": ["R-001"],
                    "observable": "o",
                    "reference_rule": "r",
                }
            ]
        )
    )
    (wd / "spec-review").mkdir(exist_ok=True)
    (wd / "spec-review" / "requirements.md").write_text(
        "# ledger review\n\nNo findings.\n"
    )
    (wd / "spec-review" / "dut_top.md").write_text("# spec review\n\nNo findings.\n")
    (wd / "spec-review" / "decisions.md").write_text(
        "# decisions\n\nNothing to resolve.\n"
    )
    return wd


def _validate_envelope(env: dict) -> None:
    env_schema = json.loads(
        (ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (ROOT / "skills/specification/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        _ENVELOPE_URI, Resource.from_contents(env_schema)
    )
    Draft202012Validator(stage_schema, registry=registry).validate(
        env
    )  # raises on invalid


def test_build_result_pass_lean_shape(tmp_path):
    wd = _spec_workdir(tmp_path)
    assert result.build_result(wd, status="pass") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "specification"
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss == {
        "top_module": "dut_top"
    }  # lean: the review is prose, the ledger a sidecar
    assert {"path": "requirements.json"} in env["artifacts"]
    assert (
        json.loads((wd / "requirements.json").read_text()) == _ROWS
    )  # re-validated, untouched


def test_build_result_reject_status_writes_fail(tmp_path):
    wd = _spec_workdir(tmp_path)
    assert result.build_result(wd, status="fail") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail" and env["stage_specific"]["fail_reason"]


def test_enumerate_artifacts_present_only(tmp_path):
    wd = _spec_workdir(tmp_path)
    constraints.derive_constraints(wd)
    (wd / "children" / "fifo.md").write_text("# child\n")
    m = json.loads((wd / "manifest.json").read_text())
    m["children"].append(
        {"name": "fifo", "doc": "children/fifo.md", "rtl_modules": ["fifo"]}
    )
    (wd / "manifest.json").write_text(json.dumps(m))
    arts = result.enumerate_artifacts(wd, top="dut_top")
    paths = {a["path"] for a in arts}
    assert {
        "design.md",
        "children",
        "check-hints",
        "spec-review",
        "manifest.json",
        "requirements.json",
        "constraints/dut_top.sdc",
        "constraints/dut_top.sgdc",
        "clocks.json",
    } <= paths
    assert all(set(a) == {"path"} for a in arts)  # the path IS the identity
    assert "intent/brainstorm.md" not in paths and "result.json" not in paths
    assert all((wd / p).exists() for p in paths)  # present-only


def test_golden_lean_against_a_real_run(tmp_path):
    # The top module's name is read from the fixture's own manifest rather than written
    # here: what this asserts is that finalize carries it through and names every present
    # artifact exactly once, which holds for whichever module the sample happens to be.
    wd = tmp_path / "specification"
    shutil.copytree(_FIX, wd)
    top = json.loads((_FIX / "manifest.json").read_text())["module"]
    assert result.build_result(wd, status="pass") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert env["stage_specific"] == {"top_module": top}
    paths = {a["path"] for a in env["artifacts"]}
    assert paths == {
        "design.md",
        "manifest.json",
        "children",
        "check-hints",
        "spec-review",
        f"constraints/{top}.sdc",
        f"constraints/{top}.sgdc",
        "requirements.json",
        "clocks.json",
        "top-io.json",
        "interconnects.json",
    }
    _validate_envelope(env)


# ── the ledger at finalize ────────────────────────────────────────────────────


def test_missing_ledger_is_blocked(tmp_path):
    wd = _spec_workdir(tmp_path)
    (wd / "requirements.json").unlink()
    assert result.finalize(wd, status="pass") == 2
    assert not (wd / "result.json").exists()


def test_invalid_ledger_is_blocked(tmp_path):
    wd = _spec_workdir(tmp_path, rows=[{**_ROWS[0], "judge": "bogus"}])
    assert result.finalize(wd, status="pass") == 2


def test_unassignable_row_is_blocked_with_its_id(tmp_path, capsys):
    # The gate resolves these; finalize never carries one forward.
    rows = [
        *_ROWS,
        {
            "id": "R-003",
            "verbatim": "storage ≤ 16 Kbit",
            "judge": "unassignable",
            "note": "no measurand",
        },
    ]
    wd = _spec_workdir(tmp_path, rows=rows)
    assert result.finalize(wd, status="pass") == 2
    assert "R-003" in capsys.readouterr().err
    assert not (wd / "result.json").exists()


def test_nan_target_is_blocked(tmp_path):
    wd = _spec_workdir(tmp_path)
    (wd / "requirements.json").write_text(
        '[{"id":"R-001","verbatim":"v","judge":"synthesis","target":{"dim":"area_um2","op":"<=","value":NaN}}]'
    )
    assert result.finalize(wd, status="pass") == 2


def test_crossrefs_regression_after_the_gate_is_blocked(tmp_path):
    # A hint pointing at a row nobody has any more: clean at the Wave 2 gate, so a failure now
    # means an artifact was edited afterwards.
    wd = _spec_workdir(tmp_path)
    (wd / "requirements.json").write_text(json.dumps([_ROWS[1]]))
    assert result.finalize(wd, status="pass") == 2


# ── early-fail entry (--fail-reason): routable fail, full artifact carry ──


def test_early_fail_writes_reason_and_carries_artifacts(tmp_path):
    wd = _spec_workdir(tmp_path)
    constraints.derive_constraints(wd)
    assert (
        result.build_result(
            wd, status="fail", fail_reason="external reference missing: /x/design.md"
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    ss = env["stage_specific"]
    assert ss["fail_reason"] == "external reference missing: /x/design.md"
    assert ss["top_module"] == "dut_top"  # from manifest.module, no derivation run
    paths = {a["path"] for a in env["artifacts"]}
    assert {
        "design.md",
        "manifest.json",
        "requirements.json",
        "constraints/dut_top.sdc",
    } <= paths
    _validate_envelope(env)


def test_reject_default_reason_unchanged(tmp_path):
    wd = _spec_workdir(tmp_path)
    result.build_result(wd, status="fail")
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "design.md gate rejected at human review"


def test_fail_without_manifest_is_blocked(tmp_path):
    rc = result.finalize(tmp_path, status="fail", fail_reason="wave-1 BLOCKED: x")
    assert rc == 2
    assert not (tmp_path / "result.json").exists()


def test_pass_ignores_fail_reason(tmp_path):
    wd = _spec_workdir(tmp_path)
    rc = result.finalize(wd, status="pass", fail_reason="should be ignored")
    assert rc == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert "fail_reason" not in env["stage_specific"]


def test_derivation_failure_on_pass_is_blocked_exit2(tmp_path):
    wd = _spec_workdir(tmp_path)
    (wd / "clocks.json").write_text(
        json.dumps(
            [{"name": "i_clk", "period_ns": "banana", "relationship": "primary"}]
        )
    )
    assert result.finalize(wd, status="pass") == 2


def test_empty_fail_reason_is_blocked(tmp_path):
    wd = _spec_workdir(tmp_path)
    rc = result.finalize(wd, status="fail", fail_reason="   ")
    assert rc == 2
    assert not (wd / "result.json").exists()


def test_unreadable_schema_blocks_instead_of_waving_a_doc_through(
    tmp_path, monkeypatch
):
    from spec import sidecar

    monkeypatch.setattr(sidecar, "_REFERENCES", tmp_path)
    assert sidecar.validate_doc("requirements.json", _ROWS)


# ── the verbs ───────────────────────────────────────────────────────────────


def test_finalize_cli_happy_path(tmp_path):
    wd = _spec_workdir(tmp_path)
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(wd), "--status", "pass"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads((wd / "result.json").read_text())["status"] == "pass"


def test_finalize_missing_required_flag_is_blocked(tmp_path):
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2  # argparse: missing --status


def test_check_ledger_prints_the_gate_view(tmp_path):
    rows = [
        *_ROWS,
        {"id": "R-003", "verbatim": "hidden tests all pass", "judge": "outside"},
        {
            "id": "R-004",
            "verbatim": "storage ≤ 16 Kbit",
            "judge": "unassignable",
            "note": "no measurand",
        },
        {
            "id": "R-005",
            "verbatim": "the reference model is authoritative",
            "judge": "human",
        },
    ]
    wd = _spec_workdir(tmp_path, rows=rows)
    r = subprocess.run(
        ["python3", str(MAIN), "check-ledger", "--workdir", str(wd)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    view = json.loads(r.stdout)
    assert view["rows"] == 5
    assert view["by_judge"] == {
        "simulation": 1,
        "synthesis": 1,
        "outside": 1,
        "unassignable": 1,
        "human": 1,
    }
    groups = {k: [x["id"] for x in v] for k, v in view["verbatim"].items()}
    assert groups == {
        "unassignable": ["R-004"],
        "outside": ["R-003"],
        "human": ["R-005"],
        "target": ["R-002"],
    }
    assert (
        view["verbatim"]["unassignable"][0]["note"] == "no measurand"
    )  # the human reads the reason


def test_check_ledger_fails_loud_on_a_bad_ledger(tmp_path):
    wd = _spec_workdir(tmp_path, rows=[{**_ROWS[0], "judge": "bogus"}])
    r = subprocess.run(
        ["python3", str(MAIN), "check-ledger", "--workdir", str(wd)],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "bogus" in (r.stdout + r.stderr)
