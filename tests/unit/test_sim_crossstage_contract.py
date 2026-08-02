# tests/unit/test_sim_crossstage_contract.py
"""Lock the simulation-plan -> simulation scaffold-spec consumer contract (spec §5).

Renders the COMMITTED producer-owned materialized fixture (simplan's real output shape) and asserts every field simulation CONSUMES, with expectations DERIVED FROM the
fixture (agent names, RM file name, the RM-inport + env-connect + observer wiring, interface
signal widths, primary_clock/reset port names). This locks the CONSUMER end; producer
generation is owned by the already-settled simplan stage (which owns/regenerates this fixture)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "skills/simulation/templates/scaffold"
FIXTURE = ROOT / "tests/unit/fixtures/simulation-plan-tpu_top"  # the plan dir
BOUNDARY = ROOT / "tests/unit/fixtures/specification-tpu_top"  # top-io + clocks
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import scaffold  # noqa: E402


def _render(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    scaffold.render(FIXTURE, out, BOUNDARY, TEMPLATES)
    spec = json.loads((FIXTURE / "tb-scaffold.json").read_text())
    spec["sequences"] = json.loads((FIXTURE / "sequences.json").read_text())
    return out, spec


def test_fixture_renders_clean(tmp_path):
    out, spec = _render(tmp_path)
    assert (out / "tb/uvm/top" / f"{spec['top']}_tb_top.sv").is_file()
    assert (out / "tests/testlist.json").is_file()


def test_agent_io_shape_consumed(tmp_path):
    """Every top-io.json data port renders into its agent's vif and txn with its own width.
    The scaffold does not restate them, so this is the whole path from the declaration."""
    out, spec = _render(tmp_path)
    module = spec["module"]
    ports = json.loads((BOUNDARY / "top-io.json").read_text())
    for ag in spec["agents"]:
        groups = set(ag["interface_groups"])
        mine = [
            p for p in ports if p["role"] == "data" and p["interface_group"] in groups
        ]
        assert mine, f"{ag['name']}: fixture gives it no data ports"
        # the derived halves live in their own includes, so a later boundary change can
        # replace them without touching the clocking blocks / formatter around them
        iface = (
            out / "tb/uvm/interface" / f"{module}_{ag['name']}_signals.svh"
        ).read_text()
        txn = (
            out / "tb/uvm/transaction" / f"{module}_{ag['name']}_fields.svh"
        ).read_text()
        for sig in mine:
            assert sig["name"] in iface, f"{ag['name']}: {sig['name']} not in the vif"
            assert sig["name"] in txn, f"{ag['name']}: {sig['name']} not in the txn"
            w = int(sig["width"])
            if w > 1:
                assert f"[{w - 1}:0] {sig['name']};" in iface, (
                    f"{ag['name']}: wrong width for {sig['name']}"
                )
        # the bench drives clock and reset: they must not reappear inside an agent
        assert "logic clk;" not in iface
        # and the stub that includes them is the agent's own to fill
        shell = (out / "tb/uvm/interface" / f"{module}_{ag['name']}_if.sv").read_text()
        assert f'`include "{module}_{ag["name"]}_signals.svh"' in shell


def test_inport_and_observer_wiring(tmp_path):
    out, spec = _render(tmp_path)
    module = spec["module"]
    rm_name = spec["rm"].get("name", "rule_rm")
    rm = (out / "tb/uvm/refmodel" / f"{module}_{rm_name}.sv").read_text()
    env = (out / "tb/uvm/env" / f"{module}_env.sv").read_text()
    obs = spec["scoreboard"]["observer"]
    for agent in spec["rm"]["inports"]:
        assert f"write_{agent}" in rm, f"RM missing write_{agent}"
        if agent != obs:
            # the one RM lives in the scoreboard
            assert f"m_{agent}_agent.ap.connect(m_scoreboard.rm.ai_{agent})" in env, (
                f"env missing inport connect for {agent}"
            )
    assert f"m_{obs}_agent.ap.connect(m_scoreboard.analysis_export)" in env, (
        f"env missing observer connect for {obs}"
    )
    # The observer feeds the RM through the scoreboard, not through a second connection:
    # one analysis port fanned out to both ingest and compare has no order between them.
    assert f"m_{obs}_agent.ap.connect(m_scoreboard.rm." not in env
    assert "m_rm" not in env, (
        "a second RM instance in the env receives what nobody predicts from"
    )


def test_primary_clock_and_reset_consumed(tmp_path):
    out, spec = _render(tmp_path)
    tb_top = (out / "tb/uvm/top" / f"{spec['top']}_tb_top.sv").read_text()
    clocks = json.loads((BOUNDARY / "clocks.json").read_text())
    primary = next(c for c in clocks if c["relationship"] == "primary")
    assert f".{primary['name']}(clk)" in tb_top  # e.g. .i_clk(clk)
    boundary = json.loads((BOUNDARY / "top-io.json").read_text())
    rst = next(p for p in boundary if p["role"] == "reset")
    drive = "rst_n" if rst["reset_polarity"] == 0 else "~rst_n"
    assert f".{rst['name']}({drive})" in tb_top


def test_every_clock_port_is_generated_and_bound(tmp_path):
    """A DUT clock port the bench does not bind compiles without an error and stops that
    domain for the whole run, so the contract is that every entry reaches tb_top."""
    out, spec = _render(tmp_path)
    tb_top = (out / "tb/uvm/top" / f"{spec['top']}_tb_top.sv").read_text()
    clocks = json.loads((BOUNDARY / "clocks.json").read_text())
    for c in [c for c in clocks if c["relationship"] != "primary"]:
        n = c["name"]
        assert f"logic {n};" in tb_top
        assert f"{n} = ~{n};" in tb_top
        assert f".{n}({n})" in tb_top
