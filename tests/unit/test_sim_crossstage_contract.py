# tests/unit/test_sim_crossstage_contract.py
"""Lock the simulation-plan -> simulation scaffold-spec consumer contract (spec §5).

Renders the COMMITTED producer-owned materialized fixture (simplan's real output shape) through
render-scaffold and asserts every field simulation CONSUMES, with expectations DERIVED FROM the
fixture (agent names, RM file name, _obs_name strip across RM-inport + env-connect + observer,
interface signal widths, primary_clock/reset port names). This locks the CONSUMER end; producer
generation is owned by the already-settled simplan stage (which owns/regenerates this fixture)."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"
TEMPLATES = ROOT / "skills/simulation/templates/scaffold"
FIXTURE = (
    ROOT / "tests/unit/fixtures/simulation-plan-tpu_top/scaffold-specification.json"
)


def _obs(
    txn, module
):  # mirror the cross-stage _obs_name strip to derive expectations from the fixture
    return txn.replace(f"{module}_", "").replace("_txn", "")


def _render(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "render-scaffold",
            "--scaffold",
            str(FIXTURE),
            "--output-dir",
            str(out),
            "--template-dir",
            str(TEMPLATES),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return out, json.loads(FIXTURE.read_text())


def test_fixture_renders_clean(tmp_path):
    out, spec = _render(tmp_path)
    assert (out / "tb/uvm/top" / f"{spec['top']}_tb_top.sv").is_file()
    assert (out / "tests/testlist.json").is_file()


def test_agent_io_shape_consumed(tmp_path):
    # _agent_io + _signal_declarations: every interface.signals[] entry renders with its width.
    out, spec = _render(tmp_path)
    module = spec["module"]
    for ag in spec["agents"]:
        iface = (out / "tb/uvm/interface" / f"{module}_{ag['name']}_if.sv").read_text()
        for sig in ag["interface"]["signals"]:
            assert sig["name"] in iface, (
                f"{ag['name']}: signal {sig['name']} not rendered"
            )
            w = int(sig.get("width", 1))
            if w > 1:
                assert f"[{w - 1}:0] {sig['name']};" in iface, (
                    f"{ag['name']}: wrong width for {sig['name']}"
                )
        # transaction.fields[] consumed too (each field name appears in the txn class)
        txn = (out / "tb/uvm/transaction" / f"{module}_{ag['name']}_txn.sv").read_text()
        for fld in ag.get("transaction", {}).get("fields", []):
            assert fld["name"] in txn, f"{ag['name']}: field {fld['name']} not rendered"


def test_obs_name_strip_inports_and_observer(tmp_path):
    out, spec = _render(tmp_path)
    module = spec["module"]
    rm_name = spec["rm"].get("name", "rule_rm")
    rm = (out / "tb/uvm/refmodel" / f"{module}_{rm_name}.sv").read_text()
    env = (out / "tb/uvm/env" / f"{module}_env.sv").read_text()
    for txn in spec["rm"]["inports"]:  # RM-inport + env-connect sites
        agent = _obs(txn, module)
        assert f"write_{agent}" in rm, f"RM missing write_{agent}"
        assert f"m_{agent}_agent.ap.connect(m_rm.ai_{agent})" in env, (
            f"env missing inport connect for {agent}"
        )
    obs = _obs(spec["scoreboard"]["compare_txn"], module)  # observer site
    assert f"m_{obs}_agent.ap.connect(m_scoreboard.analysis_export)" in env, (
        f"env missing observer connect for {obs}"
    )


def test_primary_clock_and_reset_consumed(tmp_path):
    out, spec = _render(tmp_path)
    tb_top = (out / "tb/uvm/top" / f"{spec['top']}_tb_top.sv").read_text()
    assert (
        f".{spec['primary_clock']['dut_port_name']}(clk)" in tb_top
    )  # e.g. .i_clk(clk)
    assert f".{spec['reset']['dut_port_name']}(rst_n)" in tb_top  # e.g. .i_rstn(rst_n)
