# tests/unit/test_sim_gate.py
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import _gate  # noqa: E402

SCAFFOLD = {
    "module": "m",
    "agents": [{"name": "drv", "mode": "active"}, {"name": "obs", "mode": "passive"}],
    "sequences": [{"name": "smoke", "agent": "drv"}],
}


def _materialized(tmp_path, todo=False, drop_seq=False, drop_env=False):
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
    (tmp_path / "tb/uvm/env").mkdir(parents=True)
    (tmp_path / "tb/uvm/env/m_env.sv").write_text(
        "class m_env; m_drv_agent drv; m_obs_agent obs; endclass\n"
        if not drop_env
        else "class m_env; m_drv_agent drv; endclass\n"
    )
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


def _rows(tmp_path, *dims, op=">", value=90):
    rows = [
        {
            "id": f"R-{i}",
            "verbatim": f"{d} coverage {op} {value}%",
            "judge": "simulation",
            "target": {"dim": f"coverage_{d}", "op": op, "value": value},
        }
        for i, d in enumerate(dims)
    ]
    rows.append({"id": "R-x", "verbatim": "unrelated", "judge": "rtl-design"})
    p = tmp_path / "requirements.json"
    p.write_text(json.dumps(rows))
    return _gate.coverage_rows(p)


def test_coverage_rows_are_every_targeted_simulation_row(tmp_path):
    rows = _rows(tmp_path, "line", "fsm")
    assert [r["id"] for r in rows] == ["R-0", "R-1"]


def test_a_dim_simulation_does_not_measure_is_refused_by_name(tmp_path):
    # requirements.schema.json promises that a dim a stage does not measure is "refused by
    # name there". Filtering coverage_rows on the coverage_ prefix instead dropped such a row
    # before the gate, so the engineer's bound was silently ungated and nothing complained.
    rows = [
        {
            "id": "R-9",
            "verbatim": "single-tile latency <= 80 cycles",
            "judge": "simulation",
            "target": {"dim": "single_tile_latency", "op": "<=", "value": 80},
        }
    ]
    p = tmp_path / "requirements.json"
    p.write_text(json.dumps(rows))
    selected = _gate.coverage_rows(p)
    assert [r["id"] for r in selected] == ["R-9"], "the row must reach the gate at all"
    cov = {"per_module": [dict(name="m", **{"line": 92.0})]}
    errs, judged = _gate.coverage_gate(cov, selected, "m")
    assert judged[0]["met"] is False
    assert any("single_tile_latency is bounded but" in e for e in errs)


def test_coverage_gate_pass(tmp_path):
    rows = _rows(tmp_path, "line", "cond", "fsm", "toggle")
    cov = {
        "per_module": [
            dict(name="m", **{"line": 92.0, "cond": 91.0, "fsm": 95.0, "toggle": 93.0})
        ]
    }
    errs, judged = _gate.coverage_gate(cov, rows, "m")
    assert errs == [] and all(j["met"] for j in judged) and judged[0]["actual"] == 92.0


def test_coverage_gate_uses_the_engineers_operator(tmp_path):
    # "> 90" is strict: exactly 90.0 does not pass. ">= 90" would.
    cov = {"per_module": [dict(name="m", **{"line": 90.0})]}
    errs, judged = _gate.coverage_gate(cov, _rows(tmp_path, "line"), "m")
    assert judged[0]["met"] is False and "not > 90" in errs[0]
    errs, judged = _gate.coverage_gate(cov, _rows(tmp_path, "line", op=">="), "m")
    assert errs == [] and judged[0]["met"] is True


def test_coverage_gate_below_threshold(tmp_path):
    cov = {
        "per_module": [
            dict(name="m", **{"line": 10.0, "cond": 91.0, "fsm": 95.0, "toggle": 93.0})
        ]
    }
    errs, _ = _gate.coverage_gate(cov, _rows(tmp_path, "line"), "m")
    assert any("R-0: line coverage 10.0 is not > 90" in e for e in errs)


def test_coverage_gate_null_dim_skipped(tmp_path):
    cov = {
        "per_module": [
            dict(name="m", **{"line": 92.0, "cond": 91.0, "fsm": None, "toggle": 93.0})
        ]
    }
    errs, judged = _gate.coverage_gate(cov, _rows(tmp_path, "fsm"), "m")
    assert errs == [] and judged[0] == {
        "id": "R-0",
        "met": True,
        "actual": None,
        "measured": "fsm coverage of 'm': reported N/A by urg",
    }


def test_coverage_gate_absent_dim_fails(tmp_path):
    cov = {
        "per_module": [dict(name="m", **{"line": 92.0, "cond": 91.0, "toggle": 93.0})]
    }  # fsm absent
    errs, judged = _gate.coverage_gate(cov, _rows(tmp_path, "fsm"), "m")
    assert any("fsm is bounded but" in e for e in errs)
    assert judged[0]["met"] is False


def test_coverage_gate_unbounded_dim_is_not_gated(tmp_path):
    # No row for fsm: it is reported, not judged.
    cov = {"per_module": [dict(name="m", **{"line": 92.0, "fsm": 3.0})]}
    errs, judged = _gate.coverage_gate(cov, _rows(tmp_path, "line"), "m")
    assert errs == [] and [j["id"] for j in judged] == ["R-0"]


def test_coverage_gate_not_extractable(tmp_path):
    errs, judged = _gate.coverage_gate(None, _rows(tmp_path, "line"), "m")
    assert any("not extractable" in e for e in errs) and judged == []


# ── check adequacy: the reviewer's own mark ──────────────────────────────────────
_BLOCKING = (
    "## TP-03  tb/uvm/checker/m_sb.sv:49  BLOCKING\n"
    "Compares next_token end to end and probes nothing between.\n"
)
_NOTED = "## TP-14  tb/uvm/checker/m_sb.sv:72\nThe per-step bounds dominate it.\n"


def _review(tmp_path, body):
    p = tmp_path / "check-review.md"
    p.write_text("# check-adequacy review — m\n\n" + body)
    return p


def test_a_review_with_nothing_marked_flags_nothing(tmp_path):
    assert _gate.check_review_flagged(_review(tmp_path, _NOTED)) == []


def test_a_marked_finding_is_flagged_by_its_testpoint(tmp_path):
    assert _gate.check_review_flagged(_review(tmp_path, _NOTED + _BLOCKING)) == [
        "TP-03"
    ]


def test_the_mark_is_read_off_the_heading_not_the_prose(tmp_path):
    # A finding whose body argues about blocking is not thereby blocking: the call is the
    # reviewer's, made in one place, and prose near the word cannot make it.
    body = (
        "## TP-07  tb/uvm/checker/m_sb.sv:20\n"
        "Worth BLOCKING on if it recurs, but the stimulus never reaches it this round.\n"
    )
    assert _gate.check_review_flagged(_review(tmp_path, body)) == []


def test_a_locus_with_spaces_still_parses(tmp_path):
    body = "## TP-09  plan ref: intent clause 2  BLOCKING\nNo check exists.\n"
    assert _gate.check_review_flagged(_review(tmp_path, body)) == ["TP-09"]


def test_coverage_gate_scores_the_dut_not_the_report_aggregate(tmp_path):
    """The numbers are a real run's. Its report aggregate read toggle 92.57 — the DUT plus
    eleven fully-swept ROM modules plus three agent interfaces — while the DUT itself was
    76.37. The engineer's bound was `> 90`, and the aggregate passed it: the gate shipped a
    pass on a requirement the design misses by 13 points."""
    cov = {
        "aggregate": {"line": 99.78, "cond": 97.33, "fsm": 100.0, "toggle": 92.57},
        "per_module": [
            {
                "name": "rom_wq",
                "line": 100.0,
                "cond": None,
                "fsm": None,
                "toggle": 100.0,
            },
            {"name": "m", "line": 99.6, "cond": 97.3, "fsm": 100.0, "toggle": 76.37},
            {
                "name": "m_tb_top",
                "line": 100.0,
                "cond": None,
                "fsm": None,
                "toggle": 100.0,
            },
        ],
    }
    errs, judged = _gate.coverage_gate(cov, _rows(tmp_path, "toggle"), "m")
    assert judged[0]["actual"] == 76.37 and judged[0]["met"] is False
    assert errs and "76.37" in errs[0]


def test_coverage_gate_refuses_a_report_that_does_not_carry_the_dut(tmp_path):
    """Not attributable is not a licence to score the aggregate instead."""
    cov = {
        "aggregate": {"toggle": 99.0},
        "per_module": [{"name": "somebody_else", "toggle": 99.0}],
    }
    errs, judged = _gate.coverage_gate(cov, _rows(tmp_path, "toggle"), "m")
    assert judged == [] and "not attributable" in errs[0]


def test_materialization_env_never_builds_a_declared_agent(tmp_path):
    # The renderer writes a plan-gained agent's classes and tb_top's interface and stops there;
    # the env is carried, so it neither builds nor connects it. Measured on tpu_top: that
    # compiles clean with zero warnings, so this gate is the only thing that sees it.
    errs = _gate.materialization_errors(
        _materialized(tmp_path, drop_env=True), SCAFFOLD
    )
    assert any("never names obs" in e for e in errs)
