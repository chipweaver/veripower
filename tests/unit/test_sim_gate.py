# tests/unit/test_sim_gate.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "skills/simulation/defaults.yaml"
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import _gate  # noqa: E402

SCAFFOLD = {
    "module": "m",
    "agents": [{"name": "drv", "mode": "active"}, {"name": "obs", "mode": "passive"}],
    "sequences": [{"name": "smoke", "agent": "drv"}],
}


def _materialized(tmp_path, todo=False, drop_seq=False):
    (tmp_path / "tb/uvm/seq").mkdir(parents=True)
    (tmp_path / "tb/uvm/agent").mkdir(parents=True)
    if not drop_seq:
        (tmp_path / "tb/uvm/seq/m_smoke_seq.sv").write_text(
            "class m_smoke_seq; endclass\n"
        )
    body = "// TODO(driver): fill\n" if todo else "class m_drv_driver; endclass\n"
    (tmp_path / "tb/uvm/agent/m_drv_driver.sv").write_text(body)
    (tmp_path / "tb/uvm/agent/m_drv_monitor.sv").write_text("class x; endclass\n")
    (tmp_path / "tb/uvm/agent/m_drv_agent.sv").write_text("class x; endclass\n")
    (tmp_path / "tb/uvm/agent/m_obs_monitor.sv").write_text("class x; endclass\n")
    (tmp_path / "tb/uvm/agent/m_obs_agent.sv").write_text("class x; endclass\n")
    return tmp_path


def test_materialization_clean(tmp_path):
    assert _gate.materialization_errors(_materialized(tmp_path), SCAFFOLD) == []


def test_materialization_missing_seq(tmp_path):
    errs = _gate.materialization_errors(
        _materialized(tmp_path, drop_seq=True), SCAFFOLD
    )
    assert any("missing sequence file" in e for e in errs)


def test_materialization_todo_residue(tmp_path):
    errs = _gate.materialization_errors(_materialized(tmp_path, todo=True), SCAFFOLD)
    assert any("TODO residue" in e for e in errs)


def test_materialization_active_needs_driver(tmp_path):
    wd = _materialized(tmp_path)
    (wd / "tb/uvm/agent/m_drv_driver.sv").unlink()  # active agent lost its driver
    errs = _gate.materialization_errors(wd, SCAFFOLD)
    assert any("m_drv_driver.sv" in e for e in errs)


def test_coverage_gate_pass(tmp_path):
    thr = _gate._load_thresholds(DEFAULTS)
    cov = {"aggregate": {"line": 92.0, "cond": 91.0, "fsm": 95.0, "toggle": 93.0}}
    errs, dims = _gate.coverage_gate(cov, thr)
    assert errs == [] and dims["line"]["pass"] is True


def test_coverage_gate_below_threshold(tmp_path):
    thr = _gate._load_thresholds(DEFAULTS)
    cov = {"aggregate": {"line": 10.0, "cond": 91.0, "fsm": 95.0, "toggle": 93.0}}
    errs, _ = _gate.coverage_gate(cov, thr)
    assert any("line coverage 10.0 <" in e for e in errs)


def test_coverage_gate_null_dim_skipped(tmp_path):
    thr = _gate._load_thresholds(DEFAULTS)
    cov = {"aggregate": {"line": 92.0, "cond": 91.0, "fsm": None, "toggle": 93.0}}
    errs, dims = _gate.coverage_gate(cov, thr)
    assert errs == [] and dims["fsm"]["skipped"] is True


def test_coverage_gate_absent_dim_fails(tmp_path):
    thr = _gate._load_thresholds(DEFAULTS)
    cov = {"aggregate": {"line": 92.0, "cond": 91.0, "toggle": 93.0}}  # fsm absent
    errs, dims = _gate.coverage_gate(cov, thr)
    assert any("fsm threshold configured but absent" in e for e in errs)
    assert dims["fsm"]["value"] == "absent"


def test_coverage_gate_not_extractable(tmp_path):
    thr = _gate._load_thresholds(DEFAULTS)
    errs, dims = _gate.coverage_gate(None, thr)
    assert any("not extractable" in e for e in errs) and dims == {}


# ── conformance: the reviewer's own mark ──────────────────────────────────────
_BLOCKING = (
    "## TP-03  tb/uvm/checker/m_sb.sv:49  BLOCKING\n"
    "Compares next_token end to end and probes nothing between.\n"
)
_NOTED = "## TP-14  tb/uvm/checker/m_sb.sv:72\nThe per-step bounds dominate it.\n"


def _review(tmp_path, body):
    p = tmp_path / "conformance-review.md"
    p.write_text("# conformance review — m\n\n" + body)
    return p


def test_a_review_with_nothing_marked_flags_nothing(tmp_path):
    assert _gate.conformance_flagged(_review(tmp_path, _NOTED)) == []


def test_a_marked_finding_is_flagged_by_its_testpoint(tmp_path):
    assert _gate.conformance_flagged(_review(tmp_path, _NOTED + _BLOCKING)) == ["TP-03"]


def test_the_mark_is_read_off_the_heading_not_the_prose(tmp_path):
    # A finding whose body argues about blocking is not thereby blocking: the call is the
    # reviewer's, made in one place, and prose near the word cannot make it.
    body = (
        "## TP-07  tb/uvm/checker/m_sb.sv:20\n"
        "Worth BLOCKING on if it recurs, but the stimulus never reaches it this round.\n"
    )
    assert _gate.conformance_flagged(_review(tmp_path, body)) == []


def test_a_locus_with_spaces_still_parses(tmp_path):
    body = "## TP-09  plan ref: intent clause 2  BLOCKING\nNo check exists.\n"
    assert _gate.conformance_flagged(_review(tmp_path, body)) == ["TP-09"]
