#!/usr/bin/env python3
"""Generate the UVM scaffold from the simulation-plan sidecars, for the bootstrap verb.

Renders one tree of UVM source under <output-dir>/tb/uvm/ (interfaces, transactions, drivers,
monitors, agents, sequences, tests, RM, scoreboard, env, tb_top, tb_pkg.sv, filelist.f,
generated_tests.svh, tests/testlist.json), each carrying TODO markers for the simulation agent
to fill. Consumes the scaffold-spec shape simulation-plan's materialize step produces: `rm.inports`
and `scoreboard.observer` name agents, and the `<module>_<agent>_txn` type is built here, so
nothing has to un-wrap a name to recover the identity inside it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sim import (
    _render,
)  # write_text is reached through the module so a test can patch it
from sim._guards import _agent_io, validate_ports
from sim._plan import load_plan
from sim._plan import paths as plan_paths
from sim._render import (
    _field_declarations,
    _field_macros,
    _render_template_file,
    _signal_declarations,
)


def run_scaffold(plan_dir, template_dir: Path, out_dir: Path) -> int:
    spec = load_plan(plan_dir)
    module = spec["module"]
    top = spec["top"]
    agents = spec.get("agents", [])
    if not agents:
        sys.exit(
            "[sim bootstrap] tb-scaffold.json declares no agents. Nothing would drive or observe the "
            "DUT, and the tree this renders would compile against transaction types no agent "
            "produces. Rerun simulation-plan's materialize step."
        )
    rm_cfg = spec.get("rm", {})
    sb_cfg = spec.get("scoreboard", {})
    sequences = spec.get("sequences", [])
    tests = spec.get("tests", [])

    # primary_clock + reset are REQUIRED fields in scaffold-spec.
    # Missing / malformed → fail-fast; user must rerun simulation-plan to populate.
    # Outer block missing and inner field missing are split into two try/except
    # so the error message identifies the exact path (avoids "primary_clock.primary_clock"
    # artifact when the top-level key is absent).
    try:
        primary_clock = spec["primary_clock"]
    except KeyError:
        sys.exit(
            "[sim bootstrap] scaffold-spec missing primary_clock block. "
            "Rerun simulation-plan to populate primary_clock from clocks.json "
            "(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )
    try:
        clk_port_name = primary_clock["dut_port_name"]
        period_ns_raw = primary_clock["period_ns"]
    except KeyError as e:
        sys.exit(
            f"[sim bootstrap] scaffold-spec primary_clock.{e.args[0] if e.args else 'field'} missing. "
            f"Rerun simulation-plan to populate primary_clock from clocks.json "
            f"(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )

    try:
        clk_half_period = float(period_ns_raw) / 2
    except (TypeError, ValueError):
        sys.exit(
            f"[sim bootstrap] primary_clock.period_ns is not numeric: {period_ns_raw!r}. "
            f"The schema pins it as a number; check Design/specification/clocks.json."
        )

    try:
        rst_port_name = spec["reset"]["dut_port_name"]
        rst_polarity = spec["reset"]["polarity"]
    except KeyError as e:
        sys.exit(
            f"[sim bootstrap] scaffold-spec missing reset.{e.args[0] if e.args else 'field'}. "
            f"Rerun simulation-plan to populate reset from top-io.json "
            f"(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )
    if rst_polarity not in (0, 1):
        sys.exit(
            f"[sim bootstrap] reset.polarity is {rst_polarity!r}, not 0 or 1. It comes from "
            f"top-io.json's reset_polarity; the schema pins both, so check that sidecar."
        )
    # The bench's rst_n is active-low for every DUT; an active-high port is driven inverted
    # here rather than by flipping the bench, so agents never branch on polarity.
    rst_drive = "rst_n" if rst_polarity == 0 else "~rst_n"

    extra_clocks = spec.get("additional_clocks", [])
    for c in extra_clocks:
        try:
            float(c["period_ns"])
            str(c["dut_port_name"])
        except (KeyError, TypeError, ValueError):
            sys.exit(
                f"[sim bootstrap] additional_clocks entry is malformed: {c!r}. Each needs a "
                f"dut_port_name and a numeric period_ns; rerun simulation-plan's materialize "
                f"step, which fills them from clocks.json."
            )

    rm_name = rm_cfg.get("name", "rule_rm")
    sb_name = sb_cfg.get("name", "scoreboard")
    # Determine the observer agent (passive agent whose txn is compared by scoreboard)
    obs_agent = sb_cfg.get("observer", "")
    if not obs_agent and agents:
        # Default: last agent if not specified
        obs_agent = agents[-1]["name"]

    # Inport agents for RM (active agents that feed into RM)
    rm_inports = rm_cfg.get("inports", [])

    pending: list[
        tuple[Path, str]
    ] = []  # (dest, content) staged in memory; written atomically at the end

    # --- Per-agent files ---
    for agent in agents:
        aname = agent["name"]
        mode = agent.get("mode", "active")
        # Canonical agent shape, materialized by simulation-plan's materialize-scaffold verb
        # from top-io.json grouped by interface_group. _agent_io exits on an empty interface
        # rather than rendering a TB that drives nothing.
        signals, fields = _agent_io(agent)

        base = {"MODULE": module, "TOP": top, "AGENT_NAME": aname}

        # Interface
        content = _render_template_file(
            template_dir,
            "agent_if.sv",
            {
                **base,
                "SIGNAL_DECLARATIONS": _signal_declarations(signals),
            },
        )
        dest = out_dir / "tb" / "uvm" / "interface" / f"{module}_{aname}_if.sv"
        pending.append((dest, content))

        # Transaction
        content = _render_template_file(
            template_dir,
            "agent_txn.sv",
            {
                **base,
                "FIELD_MACROS": _field_macros(fields),
                "FIELD_DECLARATIONS": _field_declarations(fields),
            },
        )
        dest = out_dir / "tb" / "uvm" / "transaction" / f"{module}_{aname}_txn.sv"
        pending.append((dest, content))

        # Monitor (all agents have a monitor)
        content = _render_template_file(template_dir, "agent_monitor.sv", base)
        dest = out_dir / "tb" / "uvm" / "agent" / f"{module}_{aname}_monitor.sv"
        pending.append((dest, content))

        # Driver (rendered for every agent so agent_agent.sv's `m_driver` type
        # declaration always resolves; a passive agent's driver class compiles but is
        # never instantiated -- agent_agent.sv guards creation with get_is_active()).
        content = _render_template_file(template_dir, "agent_driver.sv", base)
        dest = out_dir / "tb" / "uvm" / "agent" / f"{module}_{aname}_driver.sv"
        pending.append((dest, content))

        # Agent assembly
        content = _render_template_file(template_dir, "agent_agent.sv", base)
        dest = out_dir / "tb" / "uvm" / "agent" / f"{module}_{aname}_agent.sv"
        pending.append((dest, content))

    # --- Sequences ---
    for seq in sequences:
        seq_agent = seq.get("agent", agents[0]["name"])
        content = _render_template_file(
            template_dir,
            "seq.sv",
            {
                "MODULE": module,
                "TOP": top,
                "SEQ_NAME": seq["name"],
                "AGENT_NAME": seq_agent,
                "SEQ_DESC": seq.get("desc", ""),
            },
        )
        dest = out_dir / "tb" / "uvm" / "seq" / f"{module}_{seq['name']}_seq.sv"
        pending.append((dest, content))

    # --- RM ---
    # Build analysis_imp declarations for each inport
    rm_imp_decl_macros: list[str] = []  # `uvm_analysis_imp_decl(_suffix) before class
    rm_imp_lines: list[str] = []
    rm_imp_new_lines: list[str] = []
    rm_write_lines: list[str] = []
    for inport_agent in rm_inports:
        imp_name = f"ai_{inport_agent}"
        txn_type = f"{module}_{inport_agent}_txn"
        rm_imp_decl_macros.append(f"`uvm_analysis_imp_decl(_{inport_agent})")
        # Pre-substitute module/rm_name here (rendered as literals) so the
        # strict renderer doesn't see unresolved {{...}} in the joined block.
        rm_imp_lines.append(
            f"  uvm_analysis_imp_{inport_agent} #({txn_type}, {module}_{rm_name}) {imp_name};"
        )
        rm_imp_new_lines.append(f'    {imp_name} = new("{imp_name}", this);')
        rm_write_lines.append(
            f"  // Called when {inport_agent} monitor sends a transaction.\n"
            f"  virtual function void write_{inport_agent}({txn_type} txn);\n"
            f"    // TODO(rm): Process {inport_agent} input — update internal state.\n"
            f"  endfunction\n"
        )

    # If no explicit inports, create a simple single-write RM (no decl macro needed)
    if not rm_imp_lines:
        first_agent = agents[0]["name"]
        txn_type = f"{module}_{first_agent}_txn"
        rm_imp_lines.append(f"  uvm_analysis_imp #({txn_type}, {module}_{rm_name}) ai;")
        rm_imp_new_lines.append('    ai = new("ai", this);')
        rm_write_lines.append(
            f"  virtual function void write({txn_type} txn);\n"
            f"    // TODO(rm): Process input — update internal state.\n"
            f"  endfunction\n"
        )

    content = _render_template_file(
        template_dir,
        "rule_rm.sv",
        {
            "MODULE": module,
            "TOP": top,
            "RM_NAME": rm_name,
            "OBS_AGENT": obs_agent,
            "RM_IMP_DECL_MACROS": "\n".join(rm_imp_decl_macros),
            "RM_ANALYSIS_IMPS": "\n".join(rm_imp_lines),
            "RM_ANALYSIS_IMP_NEWS": "\n".join(rm_imp_new_lines),
            "RM_WRITE_FUNCTIONS": "\n".join(rm_write_lines),
        },
    )
    dest = out_dir / "tb" / "uvm" / "refmodel" / f"{module}_{rm_name}.sv"
    pending.append((dest, content))

    # --- Scoreboard ---
    content = _render_template_file(
        template_dir,
        "scoreboard.sv",
        {
            "MODULE": module,
            "TOP": top,
            "SB_NAME": sb_name,
            "RM_NAME": rm_name,
            "OBS_AGENT": obs_agent,
        },
    )
    dest = out_dir / "tb" / "uvm" / "checker" / f"{module}_{sb_name}.sv"
    pending.append((dest, content))

    # --- Env ---
    agent_decl_lines: list[str] = []
    agent_create_lines: list[str] = []
    agent_connect_lines: list[str] = []
    for agent in agents:
        aname = agent["name"]
        mode = agent.get("mode", "active")
        agent_decl_lines.append(f"  {module}_{aname}_agent m_{aname}_agent;")
        if mode == "active":
            agent_create_lines.append(
                f'    m_{aname}_agent = {module}_{aname}_agent::type_id::create("m_{aname}_agent", this);\n'
                f"    m_{aname}_agent.is_active = UVM_ACTIVE;"
            )
        else:
            agent_create_lines.append(
                f'    m_{aname}_agent = {module}_{aname}_agent::type_id::create("m_{aname}_agent", this);\n'
                f"    m_{aname}_agent.is_active = UVM_PASSIVE;"
            )
        # Connect observer agent to scoreboard
        if aname == obs_agent:
            agent_connect_lines.append(
                f"    m_{aname}_agent.ap.connect(m_scoreboard.analysis_export);"
            )
        # Inport agents feed the RM, which lives in the scoreboard. The observer is the
        # exception: its stream already arrives at the scoreboard, and connecting it here as
        # well would fan one port out to both the ingest and the compare with no order
        # between them. The scoreboard forwards that one itself.
        if aname in rm_inports and aname != obs_agent:
            agent_connect_lines.append(
                f"    m_{aname}_agent.ap.connect(m_scoreboard.rm.ai_{aname});"
            )

    content = _render_template_file(
        template_dir,
        "env.sv",
        {
            "MODULE": module,
            "TOP": top,
            "RM_NAME": rm_name,
            "SB_NAME": sb_name,
            "AGENT_DECLARATIONS": "\n".join(agent_decl_lines),
            "AGENT_CREATES": "\n".join(agent_create_lines),
            "AGENT_CONNECTS": "\n".join(agent_connect_lines),
        },
    )
    dest = out_dir / "tb" / "uvm" / "env" / f"{module}_env.sv"
    pending.append((dest, content))

    # --- Tests (generated_tests.svh) ---
    test_lines = ["// Auto-generated from tb-scaffold.json."]
    for test in tests:
        tname = test["name"]
        feature = test.get("feature", "")
        test_id = test.get("test_id", tname)
        # Build sequence start calls
        seq_calls: list[str] = []
        test_seqs = test.get("seqs", [])
        for sname in test_seqs:
            # Find the sequence's agent
            seq_agent = "default"
            for s in sequences:
                if s["name"] == sname:
                    seq_agent = s.get("agent", agents[0]["name"])
                    break
            seq_calls.append(
                f"    begin\n"
                f'      {module}_{sname}_seq seq = {module}_{sname}_seq::type_id::create("{sname}");\n'
                f"      seq.start(m_env.m_{seq_agent}_agent.m_sequencer);\n"
                f"    end"
            )
        seq_start_text = (
            "\n".join(seq_calls) if seq_calls else "    // TODO: Start sequences here."
        )

        content = _render_template_file(
            template_dir,
            "test.sv",
            {
                "MODULE": module,
                "TOP": top,
                "TEST_NAME": tname,
                "FEATURE": feature,
                "TEST_ID": test_id,
                "SEQ_START_CALLS": seq_start_text,
            },
        )
        test_lines.append(content)

    dest = out_dir / "tb" / "uvm" / "test" / "generated_tests.svh"
    pending.append((dest, "\n".join(test_lines)))

    # --- tb_top ---
    if_inst_lines: list[str] = []
    config_db_lines: list[str] = []
    for agent in agents:
        aname = agent["name"]
        if_inst_lines.append(
            f"  {module}_{aname}_if {aname}_if(.clk(clk), .rst_n(rst_n));"
        )
        config_db_lines.append(
            f'    uvm_config_db#(virtual {module}_{aname}_if)::set(null, "uvm_test_top.*", "{aname}_vif", {aname}_if);'
        )

    extra_names = [c["dut_port_name"] for c in extra_clocks]
    dut_port_map = validate_ports(
        agents, clk_port_name, rst_port_name, extra_clock_names=extra_names
    )
    extra_decls = "".join(f"  logic {n};\n" for n in extra_names)
    extra_gens = "".join(
        f"\n  initial begin\n"
        f"    {c['dut_port_name']} = 0;\n"
        f"    forever #{float(c['period_ns']) / 2:g} "
        f"{c['dut_port_name']} = ~{c['dut_port_name']};\n"
        f"  end\n"
        for c in extra_clocks
    )
    extra_ports = "".join(f",\n    .{n}({n})" for n in extra_names)

    content = _render_template_file(
        template_dir,
        "tb_top.sv",
        {
            "MODULE": module,
            "TOP": top,
            "CLK_HALF_PERIOD": f"{clk_half_period:g}",
            "CLK_PORT_NAME": clk_port_name,
            "RST_PORT_NAME": rst_port_name,
            "RST_DRIVE": rst_drive,
            "EXTRA_CLOCK_DECLS": extra_decls,
            "EXTRA_CLOCK_GENS": extra_gens,
            "EXTRA_CLOCK_PORTS": extra_ports,
            "DUT_PORT_MAP": dut_port_map,
            "IF_INSTANTIATIONS": "\n".join(if_inst_lines),
            "CONFIG_DB_SETS": "\n".join(config_db_lines),
        },
    )
    dest = out_dir / "tb" / "uvm" / "top" / f"{top}_tb_top.sv"
    pending.append((dest, content))

    # --- tb_pkg.sv ---
    txn_includes: list[str] = []
    agent_includes: list[str] = []
    for agent in agents:
        aname = agent["name"]
        txn_includes.append(f'  `include "{module}_{aname}_txn.sv"')
        agent_includes.append(f'  `include "{module}_{aname}_driver.sv"')
        agent_includes.append(f'  `include "{module}_{aname}_monitor.sv"')
        agent_includes.append(f'  `include "{module}_{aname}_agent.sv"')

    seq_includes: list[str] = []
    for seq in sequences:
        seq_includes.append(f'  `include "{module}_{seq["name"]}_seq.sv"')

    content = _render_template_file(
        template_dir,
        "tb_pkg.sv",
        {
            "MODULE": module,
            "TOP": top,
            "RM_NAME": f"{module}_{rm_name}",
            "SB_NAME": f"{module}_{sb_name}",
            "TXN_INCLUDES": "\n".join(txn_includes),
            "AGENT_INCLUDES": "\n".join(agent_includes),
            "SEQ_INCLUDES": "\n".join(seq_includes),
        },
    )
    dest = out_dir / "tb" / "uvm" / "pkg" / "tb_pkg.sv"
    pending.append((dest, content))

    # --- filelist.f ---
    if_file_lines: list[str] = []
    for agent in agents:
        aname = agent["name"]
        if_file_lines.append(f"tb/uvm/interface/{module}_{aname}_if.sv")

    content = _render_template_file(
        template_dir,
        "filelist.f",
        {
            "MODULE": module,
            "TOP": top,
            "INTERFACE_FILES": "\n".join(if_file_lines),
        },
    )
    dest = out_dir / "filelist.f"
    pending.append((dest, content))

    # --- testlist.json ---
    # Field format must match run_vcs_regression.sh:
    #   "{test_id}|{uvm_testname}|{feature_id}".format(**test)
    testlist_entries: list[dict] = []
    for test in tests:
        tname = test["name"]
        missing = [
            k
            for k in ("test_id", "feature", "feature_name", "suites")
            if not test.get(k)
        ]
        if missing:
            sys.exit(
                f"[sim bootstrap] test {tname!r} is missing {missing}. Rerun simulation-plan: "
                f"suites is authored there and feature_name is injected by "
                f"materialize-scaffold; simplan check-scaffold requires all four."
            )
        testlist_entries.append(
            {
                "test_id": test["test_id"],
                "uvm_testname": f"{module}_{tname}_test",
                "feature_id": test["feature"],
                "feature_name": test["feature_name"],
                "suites": test["suites"],
                "seqs": test.get("seqs", []),
            }
        )
    testlist = {
        "module": module,
        "top": top,
        "tests": testlist_entries,
    }
    dest = out_dir / "tests" / "testlist.json"
    pending.append((dest, json.dumps(testlist, indent=2, ensure_ascii=False)))

    # Everything above was rendered and validated in memory. Write now, and only where no file
    # is there yet: this renderer creates stubs, it does not maintain them, so once a path
    # exists it belongs to whoever filled it. On a rework the whole carried testbench is
    # already on disk, and writing over it would replace a round of authored checks with
    # `// TODO`. If a write fails mid-loop, roll back what this call wrote, so the outcome is
    # the complete new set or none of it rather than a half-tree.
    written: list[Path] = []
    kept: list[Path] = []
    try:
        for dest, content in pending:
            if dest.exists():
                kept.append(dest)
                continue
            _render.write_text(dest, content)
            written.append(dest)
    except OSError:
        for p in written:
            p.unlink(missing_ok=True)
        raise

    print(
        f"[sim bootstrap] wrote {len(written)} files in {out_dir}, kept {len(kept)} already there"
    )
    for dest in written:
        print(f"  {dest.relative_to(out_dir)}")
    return 0


def render(plan_dir, out_dir, template_dir=None) -> int:
    """Render the scaffold tree, creating only what is not there yet. Exits on a missing
    sidecar or template dir; returns run_scaffold's int (0). A run_scaffold sys.exit or raise
    propagates to the caller."""
    out_dir = Path(out_dir).resolve()
    for p in plan_paths(plan_dir):
        if not p.is_file():
            sys.exit(f"[sim bootstrap] missing {p.name}: {p}")
    if template_dir:
        tmpl_dir = Path(template_dir).resolve()
    else:
        tmpl_dir = (
            Path(__file__).resolve().parent.parent.parent / "templates" / "scaffold"
        )
    if not tmpl_dir.is_dir():
        sys.exit(f"[sim bootstrap] missing template directory: {tmpl_dir}")
    return run_scaffold(plan_dir, tmpl_dir, out_dir)
