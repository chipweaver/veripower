# tests/unit/test_sim_scaffold.py
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "skills/simulation/templates/scaffold"
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import scaffold  # noqa: E402

SPEC = {
    "module": "m",
    "top": "m_top",
    "agents": [
        {"name": "drv", "mode": "active", "interface_groups": ["drv_g"]},
        {"name": "obs", "mode": "passive", "interface_groups": ["obs_g"]},
    ],
    "sequences": [{"name": "smoke", "agent": "drv"}],
    "tests": [
        {
            "name": "t_smoke",
            "seqs": ["smoke"],
            "test_id": "T-1",
            "suites": ["smoke", "regress"],
        }
    ],
    "scoreboard": {"observer": "obs"},
    "rm": {"inports": ["drv"]},
}


TOP_IO = [
    {
        "name": "clk",
        "direction": "input",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "bench",
        "role": "clock",
    },
    {
        "name": "rst_n",
        "direction": "input",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "bench",
        "role": "reset",
        "reset_polarity": 0,
        "reset_kind": "async",
    },
    {
        "name": "req",
        "direction": "input",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "drv_g",
        "role": "data",
    },
    {
        "name": "ack",
        "direction": "output",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "obs_g",
        "role": "data",
    },
]
CLOCKS = [
    {"name": "clk", "io_delay_ns": 3.0, "period_ns": 10.0, "relationship": "primary"}
]


def write_boundary(d, top_io=None, clocks=None):
    """The specification stage root the renderer reads the DUT boundary from."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / "top-io.json").write_text(json.dumps(TOP_IO if top_io is None else top_io))
    (d / "clocks.json").write_text(json.dumps(CLOCKS if clocks is None else clocks))
    return d


def write_spec(tmp_path, spec=SPEC):
    """The plan dir: the renderer reads tb-scaffold.json + sequences.json out of it."""
    doc = dict(spec)
    (tmp_path / "sequences.json").write_text(json.dumps(doc.pop("sequences", [])))
    (tmp_path / "tb-scaffold.json").write_text(json.dumps(doc))
    return tmp_path


def render(tmp_path, spec=SPEC, top_io=None, clocks=None):
    """Render into tmp_path/out. bootstrap is the only caller in the pipeline and is covered
    as a subprocess in test_sim_bootstrap; here the subject is the renderer itself."""
    plan = write_spec(tmp_path, spec)
    boundary = write_boundary(tmp_path / "spec", top_io, clocks)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    scaffold.render(plan, out, boundary, TEMPLATES)
    return out


@pytest.mark.parametrize("width", [1, 4])
def test_inout_connection_and_transaction_keep_distinct_types_on_regeneration(
    tmp_path, width
):
    ports = [dict(p) for p in TOP_IO] + [
        {
            "name": "io_link",
            "direction": "inout",
            "width": width,
            "clock_domain": "clk",
            "interface_group": "drv_g",
            "role": "data",
        }
    ]
    out = render(tmp_path, top_io=ports)
    signals = out / "tb/uvm/interface/m_drv_signals.svh"
    fields = out / "tb/uvm/transaction/m_drv_fields.svh"
    interface = out / "tb/uvm/interface/m_drv_if.sv"
    authored = interface.read_text().replace(
        "endinterface", "  logic local_enable;\nendinterface"
    )
    interface.write_text(authored)
    for unused in range(2):
        assert "wire" in next(
            line for line in signals.read_text().splitlines() if "io_link;" in line
        )
        assert "logic" in next(
            line for line in signals.read_text().splitlines() if "req;" in line
        )
        assert "rand logic" in next(
            line for line in fields.read_text().splitlines() if "io_link;" in line
        )
        scaffold.render(tmp_path, out, tmp_path / "spec", TEMPLATES)
        assert interface.read_text() == authored

    # Boundary changes still update the derived declarations, not the author's interface.
    ports[-1].update(direction="input", width=8)
    (tmp_path / "spec/top-io.json").write_text(json.dumps(ports))
    scaffold.render(tmp_path, out, tmp_path / "spec", TEMPLATES)
    assert "logic [7:0] io_link;" in signals.read_text()
    assert "rand logic [7:0] io_link;" in fields.read_text()
    assert interface.read_text() == authored


def render_exit(tmp_path, spec=SPEC, plan_dir=None, top_io=None, clocks=None):
    """Render expecting a fail-loud exit; returns the message."""
    plan = plan_dir or write_spec(tmp_path, spec)
    boundary = write_boundary(tmp_path / "spec", top_io, clocks)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    with pytest.raises(SystemExit) as e:
        scaffold.render(plan, out, boundary, TEMPLATES)
    return str(e.value)


def test_rerender_keeps_a_filled_file(tmp_path):
    # The renderer creates stubs; it does not maintain them. bootstrap runs it every round,
    # and on a rework the whole carried testbench is already on disk, so writing over it
    # replaces a round of authored checks with `// TODO`. That happened on three consecutive
    # simulation rounds of the one real module, and cost a testpoint.
    out = render(tmp_path)
    sb = out / "tb/uvm/checker/m_scoreboard.sv"
    filled = "class m_scoreboard; // 400 lines of real implementation\nendclass\n"
    sb.write_text(filled)
    scaffold.render(tmp_path, out, tmp_path / "spec", TEMPLATES)
    assert sb.read_text() == filled


def test_rerender_adds_what_the_plan_gained(tmp_path):
    # The other half: skipping what exists must not stop a new sequence from being rendered.
    out = render(tmp_path)
    grown = json.loads(json.dumps(SPEC))
    grown["sequences"] = grown["sequences"] + [{"name": "corner", "agent": "drv"}]
    write_spec(tmp_path, grown)
    scaffold.render(tmp_path, out, tmp_path / "spec", TEMPLATES)
    assert (out / "tb/uvm/seq/m_corner_seq.sv").is_file()


def test_render_scaffold_full_tree(tmp_path):
    out = render(tmp_path)
    # interface / txn / agent / seq / env / scoreboard / rm / tb_top / pkg / filelist / testlist
    assert (out / "tb/uvm/interface/m_drv_if.sv").is_file()
    assert (out / "tb/uvm/transaction/m_drv_txn.sv").is_file()
    assert (out / "tb/uvm/agent/m_drv_driver.sv").is_file()  # active -> driver
    assert (out / "tb/uvm/agent/m_obs_driver.sv").is_file()  # rendered for all agents
    assert (out / "tb/uvm/seq/m_smoke_seq.sv").is_file()
    assert (out / "tb/uvm/top/m_top_tb_top.sv").is_file()
    assert (out / "tests/testlist.json").is_file()


def test_testlist_carries_the_authored_suites(tmp_path):
    # Nothing here is invented: suites is the plan author's judgment. This verb only copies it.
    out = render(tmp_path)
    tl = json.loads((out / "tests/testlist.json").read_text())
    assert tl["module"] == "m" and tl["top"] == "m_top"
    entry = tl["tests"][0]
    assert set(entry) == {"test_id", "uvm_testname", "suites", "seqs"}
    assert entry["uvm_testname"] == "m_t_smoke_test"
    assert entry["suites"] == SPEC["tests"][0]["suites"]


def test_testlist_missing_authored_field_fails_loud(tmp_path):
    import copy

    spec = copy.deepcopy(SPEC)
    del spec["tests"][0]["suites"]
    assert "suites" in render_exit(tmp_path, spec)


@pytest.mark.parametrize("inports", [["drv"], ["drv", "obs"]])
def test_inport_and_observer_wiring(tmp_path, inports):
    # rm.inports / scoreboard.observer name agents verbatim; the txn TYPE is built from the
    # name here, so nothing un-wraps anything.
    spec = {**SPEC, "rm": {**SPEC["rm"], "inports": inports}}
    out = render(tmp_path, spec=spec)
    rm = (out / "tb/uvm/refmodel/m_rule_rm.sv").read_text()
    assert "write_drv" in rm  # inport agent derived by stripping module_/_txn
    env = (out / "tb/uvm/env/m_env.sv").read_text()
    assert "m_obs_agent.ap.connect(m_scoreboard.analysis_export)" in env  # observer
    # One RM, and it is the scoreboard's: an env-held RM is fed by an analysis fanout whose
    # order against the scoreboard's own compare is unspecified, and the scoreboard used to
    # create a second instance of its own, so the model it predicted from saw nothing at all.
    assert (
        "m_drv_agent.ap.connect(m_scoreboard.rm.ai_drv)" in env
    )  # inport -> the one rm
    assert "m_rm" not in env

    assert "m_obs_agent.ap.connect(m_scoreboard.rm." not in env
    for agent in inports:
        assert f"write_{agent}" in rm


def test_driver_monitor_vif_key_matches_tb_top_set(tmp_path):
    # Regression: tb_top registers each agent's vif under "<agent>_vif"; the
    # driver/monitor must `get` under the same key or build_phase uvm_fatals.
    out = render(tmp_path)
    tb_top = (out / "tb/uvm/top/m_top_tb_top.sv").read_text()
    assert '"drv_vif"' in tb_top  # set side, per scaffold.py
    for agent in ("drv", "obs"):
        for kind in ("driver", "monitor"):
            sv = (out / f"tb/uvm/agent/m_{agent}_{kind}.sv").read_text()
            assert f'"{agent}_vif"' in sv, (
                f"{agent} {kind} get key must match tb_top set"
            )
            assert '"vif"' not in sv, f"{agent} {kind} must not use the bare 'vif' key"


def test_render_missing_scaffold_exits(tmp_path):
    msg = render_exit(tmp_path, plan_dir=tmp_path / "nope")
    assert "missing tb-scaffold.json" in msg


def test_atomic_rollback_on_write_error(tmp_path, monkeypatch):
    # A mid-loop OSError rolls back run_scaffold's own files; re-raises. (in-process)
    spec_path = write_spec(tmp_path)
    boundary = write_boundary(tmp_path / "spec")
    out = tmp_path / "out"
    out.mkdir()
    calls = {"n": 0}
    real_write = Path.write_text

    def _boom(path, content, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        return real_write(path, content, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _boom)
    with pytest.raises(OSError):
        scaffold.render(spec_path, out, boundary, TEMPLATES)
    # the first two written files were rolled back (none of run_scaffold's own output remains)
    assert not (out / "tb/uvm/interface/m_drv_if.sv").exists()


# ── the boundary the renderer derives, rather than the copy it used to be handed ────────
def test_every_clock_is_generated_and_bound(tmp_path):
    """A DUT clock port the bench does not bind renders as an open port, which Verilog
    accepts and VCS compiles without an error — the domain is then dead for the whole run."""
    top_io = TOP_IO + [
        {
            "name": "clk2",
            "direction": "input",
            "width": 1,
            "clock_domain": "clk2",
            "interface_group": "bench",
            "role": "clock",
        }
    ]
    clocks = CLOCKS + [
        {"name": "clk2", "io_delay_ns": 2.4, "period_ns": 8.0, "relationship": "async"}
    ]
    tb = (
        render(tmp_path, top_io=top_io, clocks=clocks)
        / "tb"
        / "uvm"
        / "top"
        / "m_top_tb_top.sv"
    ).read_text()
    assert "logic [0:0] clk2;" in tb
    assert "forever #4 clk2 = ~clk2;" in tb
    assert ".clk2(clk2)" in tb


def test_reset_polarity_is_exposed_without_changing_the_signal(tmp_path):
    """The reset schedule uses the original signal and its declared active level."""
    low = (render(tmp_path) / "tb" / "uvm" / "top" / "m_top_tb_top.sv").read_text()
    assert ".rst_n(rst_n)" in low

    top_io = [dict(p) for p in TOP_IO]
    for p_ in top_io:
        if p_["role"] == "reset":
            p_.update(name="rst", reset_polarity=1)
    high = tmp_path / "high"
    high.mkdir()
    tb = (
        render(high, top_io=top_io) / "tb" / "uvm" / "top" / "m_top_tb_top.sv"
    ).read_text()
    assert ".rst(rst)" in tb
    assert "active 1" in (high / "out/tb/uvm/interface/m_reset_ports.svh").read_text()


def test_unclaimed_data_port_exits(tmp_path):
    top_io = TOP_IO + [
        {
            "name": "orphan",
            "direction": "input",
            "width": 4,
            "clock_domain": "clk",
            "interface_group": "nobody",
            "role": "data",
        }
    ]
    msg = render_exit(tmp_path, top_io=top_io)
    assert "orphan" in msg and "no agent claims" in msg


def test_group_claimed_by_two_agents_exits(tmp_path):
    spec = {
        **SPEC,
        "agents": [
            {"name": "drv", "mode": "active", "interface_groups": ["drv_g", "obs_g"]},
            {"name": "obs", "mode": "passive", "interface_groups": ["obs_g"]},
        ],
    }
    assert "claimed by both" in render_exit(tmp_path, spec)


def test_agent_with_no_data_ports_exits(tmp_path):
    spec = {
        **SPEC,
        "agents": [
            {"name": "drv", "mode": "active", "interface_groups": ["bench"]},
            {"name": "obs", "mode": "passive", "interface_groups": ["obs_g"]},
        ],
    }
    msg = render_exit(tmp_path, spec)
    assert "no data ports" in msg


def test_clock_port_without_a_clocks_json_entry_exits(tmp_path):
    top_io = TOP_IO + [
        {
            "name": "clk2",
            "direction": "input",
            "width": 1,
            "clock_domain": "clk2",
            "interface_group": "bench",
            "role": "clock",
        }
    ]
    msg = render_exit(tmp_path, top_io=top_io)
    assert "clk2" in msg and "clocks.json" in msg


def test_reset_polarity_out_of_range_exits(tmp_path):
    top_io = [dict(p) for p in TOP_IO]
    for p_ in top_io:
        if p_["role"] == "reset":
            p_.pop("reset_polarity")
    assert "reset_polarity" in render_exit(tmp_path, top_io=top_io)


# ── a rework has to re-derive: the plan or the boundary moving must reach the SV ────────
def test_rework_regenerates_the_derived_files(tmp_path):
    """The defect this replaces: render no-clobbered everything, so a second round found the
    old tb_top on disk and kept it — the run then used a DUT instantiation, a clock set and a
    reset polarity from whenever the workdir was first created."""
    out = render(tmp_path)
    tb = out / "tb" / "uvm" / "top" / "m_top_tb_top.sv"
    assert ".rst_n(rst_n)" in tb.read_text()

    top_io = [dict(p) for p in TOP_IO]
    for p_ in top_io:
        if p_["role"] == "reset":
            p_["reset_polarity"] = 1
    scaffold.render(
        write_spec(tmp_path),
        out,
        write_boundary(tmp_path / "spec", top_io),
        TEMPLATES,
    )
    assert ".rst_n(rst_n)" in tb.read_text()
    assert "active 1" in (out / "tb/uvm/interface/m_reset_ports.svh").read_text()


def test_rework_keeps_the_authored_stubs(tmp_path):
    """The other half: what a round filled in is never overwritten, which is why the derived
    part had to move out of those files rather than the whole tree becoming regenerable."""
    out = render(tmp_path)
    sb = out / "tb" / "uvm" / "checker" / "m_m_sb.sv"
    sb.write_text("// a round's authored compare\n")
    scaffold.render(
        write_spec(tmp_path), out, write_boundary(tmp_path / "spec"), TEMPLATES
    )
    assert sb.read_text() == "// a round's authored compare\n"


def test_the_reset_schedule_is_authored_and_survives_a_rework(tmp_path):
    """tb_top is derived, so a reset placed there is gone on the next round — and a reset exit
    from a state the design only passes through is reachable no other way. The schedule is
    therefore its own stub, included after the interfaces so it can be timed against them."""
    out = render(tmp_path)
    tb = out / "tb" / "uvm" / "top" / "m_top_tb_top.sv"
    rst = out / "tb" / "uvm" / "top" / "m_reset.svh"
    assert '`include "m_reset.svh"' in tb.read_text()
    assert tb.read_text().index("m_clocks.svh") < tb.read_text().index("m_reset.svh")
    assert "TODO(reset): Drive rst_n" in rst.read_text()

    rst.write_text("// a round's own reset placement\n")
    scaffold.render(
        write_spec(tmp_path), out, write_boundary(tmp_path / "spec"), TEMPLATES
    )
    assert rst.read_text() == "// a round's own reset placement\n"


def test_the_bench_can_name_sources_the_scaffold_cannot_derive(tmp_path):
    """A DPI implementation is C, so no plan describes it and no renderer emits it — and the
    only route into the compile is filelist.f, which is derived and rewritten every round. The
    list it pulls in is therefore a stub, and what a round wrote there is still there next
    round."""
    out = render(tmp_path)
    fl = out / "filelist.f"
    src = out / "tb" / "uvm" / "tb_sources.f"
    assert "-f tb/uvm/tb_sources.f" in fl.read_text()
    assert src.is_file()

    src.write_text("tb/uvm/refmodel/m_ref.c\n")
    scaffold.render(
        write_spec(tmp_path), out, write_boundary(tmp_path / "spec"), TEMPLATES
    )
    assert src.read_text() == "tb/uvm/refmodel/m_ref.c\n"
    assert "-f tb/uvm/tb_sources.f" in fl.read_text()


def test_a_new_port_reaches_the_vif_and_the_txn_on_a_rework(tmp_path):
    out = render(tmp_path)
    sig = out / "tb" / "uvm" / "interface" / "m_drv_signals.svh"
    assert "grew" not in sig.read_text()
    top_io = TOP_IO + [
        {
            "name": "grew",
            "direction": "input",
            "width": 8,
            "clock_domain": "clk",
            "interface_group": "drv_g",
            "role": "data",
        }
    ]
    scaffold.render(
        write_spec(tmp_path),
        out,
        write_boundary(tmp_path / "spec", top_io),
        TEMPLATES,
    )
    assert "[7:0] grew;" in sig.read_text()
    assert "grew" in (out / "tb/uvm/transaction/m_drv_fields.svh").read_text()
    assert ".grew(drv_if.grew)" in (out / "tb/uvm/top/m_top_tb_top.sv").read_text()


def test_each_vif_runs_on_its_own_declared_clock_domain(tmp_path):
    """top-io.json states a clock_domain per port. Wiring every vif to the primary made a
    second-domain agent sample its ports on a clock they are not in — a race the bench
    invented, not one the DUT has."""
    top_io = [dict(p) for p in TOP_IO] + [
        {
            "name": "clk2",
            "direction": "input",
            "width": 1,
            "clock_domain": "clk2",
            "interface_group": "bench",
            "role": "clock",
        }
    ]
    for p_ in top_io:
        if p_["interface_group"] == "obs_g":
            p_["clock_domain"] = "clk2"
    clocks = CLOCKS + [
        {"name": "clk2", "io_delay_ns": 2.4, "period_ns": 8.0, "relationship": "async"}
    ]
    tb = (
        render(tmp_path, top_io=top_io, clocks=clocks)
        / "tb"
        / "uvm"
        / "top"
        / "m_clocks.svh"
    ).read_text()
    assert "assign drv_if.clk = clk;" in tb
    assert "assign obs_if.clk = clk2;" in tb


def test_agent_spanning_domains_has_an_authored_connection(tmp_path):
    top_io = [dict(p) for p in TOP_IO] + [
        {
            "name": "clk2",
            "direction": "input",
            "width": 1,
            "clock_domain": "clk2",
            "interface_group": "bench",
            "role": "clock",
        }
    ]
    for p_ in top_io:
        if p_["interface_group"] == "obs_g":
            p_["clock_domain"] = "clk2"
    clocks = CLOCKS + [
        {"name": "clk2", "io_delay_ns": 2.4, "period_ns": 8.0, "relationship": "async"}
    ]
    spec = {
        **SPEC,
        "agents": [
            {"name": "drv", "mode": "active", "interface_groups": ["drv_g", "obs_g"]},
        ],
    }
    out = render(tmp_path, spec, top_io=top_io, clocks=clocks)
    connections = (out / "tb/uvm/top/m_clocks.svh").read_text()
    assert "TODO(interface)" in connections
    assert "clk, clk2" in connections
    assert "assign drv_if.clk" not in connections


def test_clock_domain_with_no_clock_port_exits(tmp_path):
    top_io = [dict(p) for p in TOP_IO]
    for p_ in top_io:
        if p_["interface_group"] == "obs_g":
            p_["clock_domain"] = "nowhere"
    assert "nowhere" in render_exit(tmp_path, top_io=top_io)


@pytest.mark.parametrize("polarities", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_all_resets_reach_the_dut_and_interfaces(tmp_path, polarities):
    ports = [dict(p) for p in TOP_IO if p["role"] != "reset"]
    for i, name in enumerate(("clear_core", "clear_io")):
        ports.append(
            {
                "name": name,
                "direction": "input",
                "width": 1,
                "clock_domain": "clk",
                "interface_group": "bench",
                "role": "reset",
                "reset_kind": "sync" if i else "async",
                "reset_polarity": polarities[i],
            }
        )
    for reverse in (False, True):
        case = tmp_path / str(reverse)
        case.mkdir()
        out = render(case, top_io=list(reversed(ports)) if reverse else ports)
        tb = (out / "tb/uvm/top/m_top_tb_top.sv").read_text()
        declarations = (out / "tb/uvm/interface/m_reset_ports.svh").read_text()
        for i, name in enumerate(("clear_core", "clear_io")):
            assert tb.count(f".{name}({name})") == 3  # DUT and both interfaces
            assert (
                f"input logic [0:0] {name}  // active {polarities[i]}" in declarations
            )
        assert "rst_n" not in tb


def test_reset_declarations_update_without_replacing_authored_work(tmp_path):
    out = render(tmp_path)
    interface = out / "tb/uvm/interface/m_drv_if.sv"
    authored = interface.read_text() + "// authored clocking and observation logic\n"
    interface.write_text(authored)
    reset = out / "tb/uvm/top/m_reset.svh"
    reset.write_text("// authored reset sequence\n")
    ports = [dict(p) for p in TOP_IO]
    ports.append({**ports[1], "name": "reset_other", "reset_polarity": 1})
    scaffold.render(
        write_spec(tmp_path), out, write_boundary(tmp_path / "spec", ports), TEMPLATES
    )
    assert (
        interface.read_text() == authored
        and reset.read_text() == "// authored reset sequence\n"
    )
    assert (
        "input logic [0:0] reset_other"
        in (out / "tb/uvm/interface/m_reset_ports.svh").read_text()
    )
    assert (out / "tb/uvm/top/m_top_tb_top.sv").read_text().count(
        ".reset_other(reset_other)"
    ) == 3


def test_a_boundary_without_reset_does_not_acquire_one(tmp_path):
    out = render(tmp_path, top_io=[p for p in TOP_IO if p["role"] != "reset"])
    tb = (out / "tb/uvm/top/m_top_tb_top.sv").read_text()
    assert "rst_n" not in tb
    assert not (out / "tb/uvm/interface/m_reset_ports.svh").read_text().strip()
    assert "TODO" not in (out / "tb/uvm/top/m_reset.svh").read_text()


def test_reset_outputs_are_observed_not_scheduled_by_the_bench(tmp_path):
    ports = [dict(p) for p in TOP_IO]
    ports.append({**ports[1], "name": "reset_child_n", "direction": "output"})
    out = render(tmp_path, top_io=ports)
    assert (
        ".reset_child_n(reset_child_n)"
        in (out / "tb/uvm/top/m_top_tb_top.sv").read_text()
    )
    assert (
        "input logic [0:0] reset_child_n"
        in (out / "tb/uvm/interface/m_reset_ports.svh").read_text()
    )
    assert "Drive reset_child_n" not in (out / "tb/uvm/top/m_reset.svh").read_text()


def test_reset_width_and_bidirectional_net_are_preserved(tmp_path):
    ports = [dict(p) for p in TOP_IO]
    ports[1].update(name="clear_lanes", width=3)
    ports.append(
        {**ports[1], "name": "board_reset_n", "width": 1, "direction": "inout"}
    )
    out = render(tmp_path, top_io=ports)
    tb = (out / "tb/uvm/top/m_top_tb_top.sv").read_text()
    declarations = (out / "tb/uvm/interface/m_reset_ports.svh").read_text()
    assert "logic [2:0] clear_lanes;" in tb
    assert "wire [0:0] board_reset_n;" in tb
    assert "input logic [2:0] clear_lanes" in declarations
    assert ".clear_lanes(clear_lanes)" in tb and ".board_reset_n(board_reset_n)" in tb


def test_passive_driver_is_reusable_without_an_unused_authoring_task(tmp_path):
    out = render(tmp_path)
    active = (out / "tb/uvm/agent/m_drv_driver.sv").read_text()
    passive = (out / "tb/uvm/agent/m_obs_driver.sv").read_text()
    assert "TODO(driver)" in active
    assert "TODO" not in passive
    assert "UNIMPLEMENTED_DRIVER" in active and "UNIMPLEMENTED_DRIVER" in passive
    assert "m_obs_driver" in (out / "tb/uvm/pkg/tb_pkg.sv").read_text()


def test_internal_domain_requires_authored_observation_not_an_oscillator(tmp_path):
    from sim.checks import materialization_errors

    ports = [dict(p) for p in TOP_IO]
    for port in ports:
        if port["interface_group"] == "obs_g":
            port["clock_domain"] = "divided"
    clocks = CLOCKS + [
        {
            "name": "divided",
            "period_ns": 20,
            "relationship": "synchronous-related",
            "generated": True,
        }
    ]
    out = render(tmp_path, top_io=ports, clocks=clocks)
    connections = out / "tb/uvm/top/m_clocks.svh"
    top = out / "tb/uvm/top/m_top_tb_top.sv"
    assert "divided" not in top.read_text()
    assert "assign obs_if.clk" not in connections.read_text()
    assert any("m_clocks.svh" in e for e in materialization_errors(out, SPEC))
    authored = (
        "\n".join(
            line for line in connections.read_text().splitlines() if "TODO" not in line
        )
        + "\nassign obs_if.clk = u_dut.actual_divider;\n"
    )
    connections.write_text(authored)
    clocks[0] = {**clocks[0], "period_ns": 12}
    scaffold.render(
        tmp_path, out, write_boundary(tmp_path / "spec", ports, clocks), TEMPLATES
    )
    assert connections.read_text() == authored
    assert "forever #6 clk = ~clk" in top.read_text()
    assert not any("m_clocks.svh" in e for e in materialization_errors(out, SPEC))


def test_clock_output_is_connected_but_not_driven(tmp_path):
    ports = [dict(p) for p in TOP_IO]
    ports.append(
        {
            "name": "out_clk",
            "direction": "output",
            "width": 1,
            "clock_domain": "out_clk",
            "interface_group": "bench",
            "role": "clock",
        }
    )
    for p in ports:
        if p["interface_group"] == "obs_g":
            p["clock_domain"] = "out_clk"
    clocks = CLOCKS + [
        {
            "name": "out_clk",
            "period_ns": 20,
            "relationship": "synchronous-related",
            "generated": True,
        }
    ]
    out = render(tmp_path, top_io=ports, clocks=clocks)
    top = (out / "tb/uvm/top/m_top_tb_top.sv").read_text()
    assert ".out_clk(out_clk)" in top
    assert "out_clk = " not in top
    assert (
        "assign obs_if.clk = out_clk;" in (out / "tb/uvm/top/m_clocks.svh").read_text()
    )


def test_generated_primary_needs_no_top_level_clock_port(tmp_path):
    ports = [{**p, "clock_domain": "internal"} for p in TOP_IO if p["role"] != "clock"]
    clocks = [
        {
            "name": "internal",
            "period_ns": 10,
            "relationship": "primary",
            "generated": True,
        }
    ]
    out = render(tmp_path, top_io=ports, clocks=clocks)
    top = (out / "tb/uvm/top/m_top_tb_top.sv").read_text()
    assert "forever #" not in top
    assert ".internal(" not in top
    assert ".rst_n(rst_n)" in top and ".req(drv_if.req)" in top
