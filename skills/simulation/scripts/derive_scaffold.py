#!/usr/bin/env python3
"""Generate the full UVM scaffold from scaffold-specification.json.

Reads scaffold-specification.json (produced by the simulation-plan agent after
Plan Gate) and renders one tree of UVM source under <output-dir>/tb/uvm/:
interfaces, transactions, drivers, monitors, agents, sequences, tests, RM,
scoreboard, env, tb_top, tb_pkg.sv, filelist.f, generated_tests.svh,
tests/testlist.json — each with TODO markers for the simulation agent to fill.

Companion script (lives under simulation-plan/scripts/, run by the
simulation-plan agent before this script):
- derive_plan_data.py — extracts structured fields from design.md into
  plan-data.json; its `clocks[]` / `interfaces[]` flow into
  scaffold-specification.json (primary_clock / reset) that this script consumes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# File-I/O helpers (small enough to duplicate; see project pass-2 verdict).
# ---------------------------------------------------------------------------


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Strict template renderer
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _render_strict(text: str, mapping: dict[str, str]) -> str:
    """Replace every {{KEY}} placeholder using mapping. Raises on unknown key.

    Replaces the previous naive str.replace approach that silently passed
    unresolved placeholders through to the SV output. Template syntax stays
    {{KEY}} (rather than {KEY}) because SystemVerilog uses single braces
    extensively, e.g. `{8'h0F, x, y}`.
    """

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in mapping:
            raise KeyError(f"Unresolved placeholder {{{{{key}}}}} in template")
        return str(mapping[key])

    return _PLACEHOLDER_RE.sub(repl, text)


def _render_template_file(
    template_dir: Path, template_name: str, mapping: dict[str, str]
) -> str:
    tmpl_path = template_dir / template_name
    if not tmpl_path.is_file():
        sys.exit(f"scaffold: missing template file: {tmpl_path}")
    return _render_strict(read_text(tmpl_path), mapping)


# ---------------------------------------------------------------------------
# SV emission helpers
# ---------------------------------------------------------------------------


def _signal_declarations(signals: list[dict]) -> str:
    """Generate SystemVerilog signal declarations from interface signal list."""
    lines = []
    for sig in signals:
        name = sig["name"]
        width = int(sig.get("width", 1))
        if width > 1:
            lines.append(f"  logic [{width - 1}:0] {name};")
        else:
            lines.append(f"  logic        {name};")
    return "\n".join(lines)


def _field_declarations(fields: list[dict]) -> str:
    """Generate transaction field declarations."""
    lines = []
    for f in fields:
        name = f["name"]
        typ = f.get("type", "logic")
        width = int(f.get("width", 1))
        rand_prefix = "rand " if f.get("rand", False) else ""
        if typ in ("int", "int unsigned"):
            lines.append(f"  {rand_prefix}{typ} {name};")
        elif width > 1:
            lines.append(f"  {rand_prefix}logic [{width - 1}:0] {name};")
        else:
            lines.append(f"  {rand_prefix}logic        {name};")
    return "\n".join(lines)


def _field_macros(fields: list[dict]) -> str:
    """Generate `uvm_field_int macros for transaction fields."""
    lines = []
    for f in fields:
        lines.append(f"    `uvm_field_int({f['name']}, UVM_ALL_ON)")
    return "\n".join(lines)


def _agent_io(agent: dict) -> tuple[list[dict], list[dict]]:
    """Read the canonical agent I/O shape materialized by simulation-plan's
    materialize_scaffold.py: agent["interface"]["signals"] = [{name, width}] and
    agent["transaction"]["fields"] = [{name, width, type?, rand?}].

    Fail loud if interface.signals is missing/empty: a degenerate empty interface is
    root cause A (TB compiles but is functionally empty, sim crashes downstream). The
    materializer guarantees non-empty signals or fails earlier; this guards the
    primitive for any direct caller and any pre-materialize scaffold-spec.
    """
    aname = agent.get("name", "<unnamed>")
    signals = agent.get("interface", {}).get("signals")
    if not signals:
        sys.exit(
            f"scaffold: agent {aname!r} has no interface.signals. Rerun simulation-plan's "
            f"materialize step (simplan materialize-scaffold): agents declare interface_groups and "
            f"the materializer fills signals from plan-data.json.interfaces[] "
            f"(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )
    fields = agent.get("transaction", {}).get("fields", [])
    return signals, fields


def _check_str_or_omitted(value, field: str, module: str) -> None:
    """Backstop: scoreboard.compare_txn must be a single '<module>_<agent>_txn' string
    (or omitted). A list/dict reaching the bare .replace() below crashes with an opaque
    AttributeError; fail loud instead. Primary enforcement is the sim-plan validate_scaffold
    gate — this guards gate-bypass callers (root cause A precedent: gate + consumer guard)."""
    if value not in (None, "") and not isinstance(value, str):
        sys.exit(
            f"scaffold: {field} must be a single '{module}_<agent>_txn' string (or omitted), "
            f"got {type(value).__name__} {value!r}. Re-run simulation-plan (simplan check-scaffold "
            f"gate). See skills/simulation-plan/SKILL.md scaffold-spec contract."
        )


def _check_list_or_omitted(value, field: str) -> None:
    """Backstop: rm.inports / tests[].seqs must be a list (or omitted). A bare string
    silently iterates character-by-character into garbage SV; fail loud instead."""
    if value not in (None, "") and not isinstance(value, list):
        sys.exit(
            f"scaffold: {field} must be a list (or omitted), got {type(value).__name__} "
            f"{value!r}. A bare string silently iterates character-by-character. Re-run "
            f"simulation-plan (simplan check-scaffold gate)."
        )


def validate_ports(agents: list[dict], clk_port_name: str, rst_port_name: str) -> str:
    """Validate per-agent signal names and build the DUT port-map block.

    Fail loud (sys.exit) on a signal colliding with the clock/reset port name or
    duplicated across agents. Called during the in-memory render pass *before any file
    is written*, so a collision leaves nothing on disk (U1 atomicity). Returns the
    dut_port_map string for tb_top (leading ',\\n' so it concatenates after .rst(rst_n)).
    """
    dut_port_lines: list[str] = []
    seen_signals: set[str] = {clk_port_name, rst_port_name}
    first_owner: dict[str, str] = {}
    for agent in agents:
        aname = agent["name"]
        signals, _ = _agent_io(agent)
        for s in signals:
            sig = s["name"]
            if sig in {clk_port_name, rst_port_name}:
                sys.exit(
                    f"scaffold: agent '{aname}' signal '{sig}' collides with "
                    f"clock/reset port name (clk={clk_port_name!r}, rst={rst_port_name!r}). "
                    f"Rename the signal in scaffold-spec or fix primary_clock.dut_port_name / "
                    f"reset.dut_port_name to disambiguate."
                )
            if sig in seen_signals:
                sys.exit(
                    f"scaffold: signal '{sig}' duplicated across agents "
                    f"(first declared in '{first_owner[sig]}', conflict in '{aname}'). "
                    f"Adjust the agents' interface_groups in scaffold-specification.json so "
                    f"the groups do not overlap, then re-run simplan materialize-scaffold "
                    f"(an agent's signals must be unique within the scaffold)."
                )
            seen_signals.add(sig)
            first_owner[sig] = aname
            dut_port_lines.append(f"    .{sig}({aname}_if.{sig}),")
    if dut_port_lines:
        dut_port_lines[-1] = dut_port_lines[-1].rstrip(",")
        return ",\n" + "\n".join(dut_port_lines)
    return ""


# ---------------------------------------------------------------------------
# Scaffold renderer (main logic)
# ---------------------------------------------------------------------------


def run_scaffold(plan_path: Path, template_dir: Path, out_dir: Path) -> int:
    spec = json.loads(read_text(plan_path))
    module = spec["module"]
    top = spec["top"]
    agents = spec.get("agents", [])
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
            "scaffold: scaffold-spec missing primary_clock block. "
            "Rerun simulation-plan to populate primary_clock from plan-data.json.clocks[] "
            "(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )
    try:
        clk_port_name = primary_clock["dut_port_name"]
        period_ns_raw = primary_clock["period_ns"]
    except KeyError as e:
        sys.exit(
            f"scaffold: scaffold-spec primary_clock.{e.args[0] if e.args else 'field'} missing. "
            f"Rerun simulation-plan to populate primary_clock from plan-data.json.clocks[] "
            f"(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )

    try:
        clk_half_period = float(period_ns_raw) / 2
    except (TypeError, ValueError):
        sys.exit(
            f"scaffold: primary_clock.period_ns is not numeric: {period_ns_raw!r}. "
            f"Check design.md §1.6 'SDC period (ns)' cell value (expected e.g. '10.0')."
        )

    try:
        rst_port_name = spec["reset"]["dut_port_name"]
    except KeyError:
        sys.exit(
            "scaffold: scaffold-spec missing reset.dut_port_name. "
            "Rerun simulation-plan to populate reset from plan-data.json.interfaces[] "
            "(see skills/simulation-plan/SKILL.md scaffold-spec contract)."
        )

    rm_name = rm_cfg.get("name", "rule_rm")
    sb_name = sb_cfg.get("name", "scoreboard")
    # Determine the observer agent (passive agent whose txn is compared by scoreboard)
    raw_cmp = sb_cfg.get("compare_txn", "")
    _check_str_or_omitted(raw_cmp, "scoreboard.compare_txn", module)
    obs_agent = (raw_cmp or "").replace(f"{module}_", "").replace("_txn", "")
    if not obs_agent and agents:
        # Default: last agent if not specified
        obs_agent = agents[-1]["name"]

    # Inport agents for RM (active agents that feed into RM)
    rm_inports = rm_cfg.get("inports", [])
    _check_list_or_omitted(rm_inports, "rm.inports")

    pending: list[
        tuple[Path, str]
    ] = []  # (dest, content) staged in memory; written atomically at the end

    # --- Per-agent files ---
    for agent in agents:
        aname = agent["name"]
        mode = agent.get("mode", "active")
        # Canonical agent shape (materialized by simulation-plan's materialize_scaffold.py
        # from plan-data.json.interfaces[] grouped by interface_group). _agent_io fails
        # loud on an empty interface (root cause A) — no silent degenerate scaffold.
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
        seq_agent = seq.get("agent", agents[0]["name"] if agents else "default")
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
    for inport_txn in rm_inports:
        # Extract agent name from txn name (e.g. "ctrl_txn" → "ctrl")
        inport_agent = inport_txn.replace(f"{module}_", "").replace("_txn", "")
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
        first_agent = agents[0]["name"] if agents else "default"
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
        # Connect inport agents to RM
        for inport_txn in rm_inports:
            inport_agent = inport_txn.replace(f"{module}_", "").replace("_txn", "")
            if aname == inport_agent:
                imp_name = f"ai_{inport_agent}"
                agent_connect_lines.append(
                    f"    m_{aname}_agent.ap.connect(m_rm.{imp_name});"
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
    test_lines = ["// Auto-generated from scaffold-specification.json."]
    for test in tests:
        tname = test["name"]
        feature = test.get("feature", "")
        test_id = test.get("test_id", tname)
        # Build sequence start calls
        seq_calls: list[str] = []
        test_seqs = test.get("seqs", [])
        _check_list_or_omitted(test_seqs, "tests[].seqs")
        for sname in test_seqs:
            # Find the sequence's agent
            seq_agent = "default"
            for s in sequences:
                if s["name"] == sname:
                    seq_agent = s.get(
                        "agent", agents[0]["name"] if agents else "default"
                    )
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

    dut_port_map = validate_ports(agents, clk_port_name, rst_port_name)

    content = _render_template_file(
        template_dir,
        "tb_top.sv",
        {
            "MODULE": module,
            "TOP": top,
            "CLK_HALF_PERIOD": f"{clk_half_period:g}",
            "CLK_PORT_NAME": clk_port_name,
            "RST_PORT_NAME": rst_port_name,
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
    #   "{test_id}|{uvm_testname}|{feature_id}|{class}".format(**test)
    # Also needs: suites (["smoke","regress"] or ["regress"])
    testlist_entries: list[dict] = []
    smoke_budget = 2
    for test in tests:
        tname = test["name"]
        feature = test.get("feature", "")
        test_id = test.get("test_id", tname)
        uvm_testname = f"{module}_{tname}_test"
        # First N tests get smoke suite
        if smoke_budget > 0:
            suites = ["smoke", "regress"]
            smoke_budget -= 1
        else:
            suites = ["regress"]
        testlist_entries.append(
            {
                "test_id": test_id,
                "uvm_testname": uvm_testname,
                "feature_id": feature,
                "feature_name": feature,
                "class": "happy",
                "suites": suites,
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

    # Atomic commit: everything above rendered + validated in memory. Write now; if any
    # write fails mid-loop, roll back the files already written so none of run_scaffold's own
    # rendered files remain (bootstrap-deployed infra/dirs are untouched) rather than a half-tree
    # (U1: "either nothing, or the complete tree" -- scoped to this renderer's own output).
    written: list[Path] = []
    try:
        for dest, content in pending:
            write_text(dest, content)
            written.append(dest)
    except OSError:
        for p in written:
            p.unlink(missing_ok=True)
        raise

    print(f"scaffold: generated {len(pending)} files in {out_dir}")
    for dest, _ in pending:
        print(f"  {dest.relative_to(out_dir)}")
    return 0


# ---------------------------------------------------------------------------
# CLI + main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Render UVM scaffold from scaffold-specification.json."
    )
    p.add_argument("--plan", required=True, help="Path to scaffold-specification.json.")
    p.add_argument("--output-dir", required=True, help="Verification output directory.")
    p.add_argument("--template-dir", help="Path to scaffold template directory.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir).resolve()

    plan_path = Path(args.plan).resolve()
    if not plan_path.is_file():
        sys.exit(f"scaffold: missing scaffold-specification.json: {plan_path}")

    if args.template_dir:
        tmpl_dir = Path(args.template_dir).resolve()
    else:
        # Default: templates/scaffold/ relative to this script
        tmpl_dir = Path(__file__).resolve().parent.parent / "templates" / "scaffold"
    if not tmpl_dir.is_dir():
        sys.exit(f"scaffold: missing template directory: {tmpl_dir}")

    return run_scaffold(plan_path, tmpl_dir, out_dir)


if __name__ == "__main__":
    sys.exit(main())
