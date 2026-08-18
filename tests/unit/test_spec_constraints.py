# tests/unit/test_spec_constraints.py
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"

sys.path.insert(0, str(ROOT / "skills" / "specification" / "scripts"))
import pytest  # noqa: E402
from spec import constraints  # noqa: E402


def _run(workdir, check=True):
    return subprocess.run(
        ["python3", str(MAIN), "derive-constraints", "--workdir", str(workdir)],
        capture_output=True,
        text=True,
        check=check,
    )


def _clk(name, period_ns, relationship="primary", generated=False, role=""):
    """One clocks.json entry. `generated` is explicit: the emitters read it directly, and
    only load_clocks() defaults the omitted key."""
    return {
        "name": name,
        "period_ns": period_ns,
        "relationship": relationship,
        "generated": generated,
        "role": role,
    }


def _port(name, direction, role, domain="clk", width=1, group="cfg", **kw):
    e = {
        "name": name,
        "direction": direction,
        "width": width,
        "clock_domain": domain,
        "interface_group": group,
        "role": role,
    }
    e.update(kw)
    return e


_DEFAULT_CLOCKS = [_clk("clk", 10.0, role="primary clock")]
_CLK_PORT = _port("clk", "input", "clock")


def _wd(tmp_path, ports, clocks=None, write_clocks=True, write_io=True):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "m",
                "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
            }
        )
    )
    if write_clocks:
        (tmp_path / "clocks.json").write_text(
            json.dumps(_DEFAULT_CLOCKS if clocks is None else clocks, indent=2)
        )
    if write_io:
        (tmp_path / "top-io.json").write_text(json.dumps(ports, indent=2))
    return tmp_path


def test_core_clocks_and_io_delays(tmp_path):
    ports = [
        _CLK_PORT,
        _port("din", "input", "data", width=8, protocol="APB3"),
        _port("dout", "output", "data", width=8, protocol="APB3"),
    ]
    summary = json.loads(_run(_wd(tmp_path, ports)).stdout)
    assert summary == {"top": "m", "clocks": 1, "data_ports": 2, "resets": 0}
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "create_clock -name clk -period 10.0 [get_ports clk]" in sdc
    assert "set_input_delay  3.0 -clock clk [get_ports {din}]" in sdc
    assert "set_output_delay 3.0 -clock clk [get_ports {dout}]" in sdc
    assert "clock -name clk -period 10.0 -edge {0 5.0}" in sgdc
    assert "abstract_port -ports {din dout} -clock clk" in sgdc
    # data/clock split exact via role: clk gets no IO delay
    assert "[get_ports {clk}]" not in sdc


def test_a_bus_is_constrained_by_its_base_name(tmp_path):
    # `get_ports token_in` selects every bit of the bus; `get_ports token_in[4:0]`
    # selects nothing (measured on PrimeTime M-2016.12-SP1: 5 ports vs 0 + SEL-005).
    # The name arrives here already stripped — read_sidecar rejects a bracketed one.
    ports = [_CLK_PORT, _port("token_in", "input", "data", width=5)]
    _run(_wd(tmp_path, ports))
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_input_delay  3.0 -clock clk [get_ports {token_in}]" in sdc


def test_a_bit_range_in_a_name_never_reaches_the_sdc(tmp_path):
    # The verb refuses the file rather than emitting a selector that matches nothing.
    ports = [_CLK_PORT, _port("token_in[4:0]", "input", "data", width=5)]
    r = _run(_wd(tmp_path, ports), check=False)
    assert r.returncode != 0
    assert "bit range" in (r.stderr + r.stdout)
    assert not (tmp_path / "constraints" / "m.sdc").exists()


def test_async_reset_emits_async_flag(tmp_path):
    ports = [
        _CLK_PORT,
        _port("rst_n", "input", "reset", reset_polarity=0, reset_kind="async"),
        _port("din", "input", "data", width=8),
    ]
    summary = json.loads(_run(_wd(tmp_path, ports)).stdout)
    assert summary["resets"] == 1
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name rst_n -value 0 -async" in sgdc
    assert "abstract_port -ports rst_n -clock clk -reset rst_n" in sgdc


def test_sync_reset_drops_async_flag(tmp_path):
    ports = [
        _CLK_PORT,
        _port("rst", "input", "reset", reset_polarity=1, reset_kind="sync"),
        _port("din", "input", "data", width=8),
    ]
    _run(_wd(tmp_path, ports))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name rst -value 1\n" in sgdc  # no -async
    assert "-async" not in sgdc.split("reset -name rst")[1].split("\n")[0]


def test_no_reset_ports_emits_no_reset_section(tmp_path):
    ports = [_CLK_PORT, _port("din", "input", "data", width=8)]
    _run(_wd(tmp_path, ports))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name" not in sgdc


def test_async_clock_groups(tmp_path):
    ports = [
        _CLK_PORT,
        _port("clk_io", "input", "clock", domain="clk_io"),
        _port("din", "input", "data", width=8),
    ]
    clocks = [
        _clk("clk", 10.0),
        _clk("clk_io", 20.0, "async", role="io clock"),
    ]
    _run(_wd(tmp_path, ports, clocks))
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_clock_groups -asynchronous" in sdc
    assert "-group [get_clocks {clk}]" in sdc
    assert "-group [get_clocks clk_io]" in sdc


def test_generated_clock_skips_create_clock(tmp_path):
    ports = [_CLK_PORT, _port("din", "input", "data", width=8)]
    clocks = [
        _clk("clk", 10.0),
        _clk("clk_div2", 20.0, "synchronous-related", generated=True),
    ]
    json.loads(_run(_wd(tmp_path, ports, clocks)).stdout)
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "create_clock -name clk_div2" not in sdc
    assert "create_generated_clock clk_div2: deferred to RTL" in sdc
    assert (
        "create_clock -name clk -period 10.0" in sdc
    )  # the real top clock still emitted
    # SGDC symmetrically skips the generated clock
    assert "clock -name clk_div2" not in sgdc
    assert "clock -name clk -period 10.0 -edge {0 5.0}" in sgdc


def test_generated_flag_may_be_omitted(tmp_path):
    # `generated` is optional in the schema; load_clocks defaults it to False, so an entry
    # written without the key must behave exactly like generated: false.
    lean = [{"name": "clk", "period_ns": 10.0, "relationship": "primary"}]
    ports = [_CLK_PORT, _port("din", "input", "data", width=8)]
    proc = _run(_wd(tmp_path, ports, lean), check=False)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "create_clock -name clk -period 10.0 [get_ports clk]" in sdc


# ---------- clocks.json contract violations (schema-enforced) ----------


def test_fail_loud_missing_clocks_json(tmp_path):
    proc = _run(_wd(tmp_path, [_CLK_PORT], write_clocks=False), check=False)
    assert proc.returncode != 0 and "clocks.json" in proc.stderr


def test_fail_loud_empty_clocks_json(tmp_path):
    # minItems: 1 — an empty array is a missing clock definition, not "no clocks".
    proc = _run(_wd(tmp_path, [_CLK_PORT], []), check=False)
    assert proc.returncode != 0 and "clocks.json" in proc.stderr


def test_fail_loud_invalid_relationship(tmp_path):
    # An invalid/misspelled relationship must fail loud, not silently fall into the
    # synchronous group (which would drop a needed set_clock_groups -asynchronous).
    bad = [_clk("clk", 10.0, "related")]
    proc = _run(_wd(tmp_path, [_CLK_PORT], bad), check=False)
    assert proc.returncode != 0 and "relationship" in proc.stderr


def test_fail_loud_string_period(tmp_path):
    # period_ns is a number: a quoted value must be rejected here, not float()-ed later.
    bad = [{**_clk("clk", 10.0), "period_ns": "10.0"}]
    proc = _run(_wd(tmp_path, [_CLK_PORT], bad), check=False)
    assert proc.returncode != 0 and "period_ns" in proc.stderr


def test_fail_loud_misspelled_clock_key(tmp_path):
    # additionalProperties: false — a mistyped key must name itself instead of defaulting.
    bad = [{**_clk("clk", 10.0), "peroid_ns": 10.0}]
    proc = _run(_wd(tmp_path, [_CLK_PORT], bad), check=False)
    assert proc.returncode != 0 and "peroid_ns" in proc.stderr


def test_fail_loud_no_primary_clock(tmp_path):
    # Not schema-expressible; load_clocks enforces it.
    bad = [_clk("clk", 10.0, "synchronous-related")]
    proc = _run(_wd(tmp_path, [_CLK_PORT], bad), check=False)
    assert proc.returncode != 0 and "primary" in proc.stderr


def test_fail_loud_two_primary_clocks(tmp_path):
    bad = [_clk("clk", 10.0), _clk("clk2", 20.0)]
    proc = _run(_wd(tmp_path, [_CLK_PORT], bad), check=False)
    assert proc.returncode != 0 and "primary" in proc.stderr


def test_fail_loud_malformed_clocks_json(tmp_path):
    wd = _wd(tmp_path, [_CLK_PORT], write_clocks=False)
    (wd / "clocks.json").write_text("[{,]")
    proc = _run(wd, check=False)
    assert proc.returncode != 0 and "clocks.json" in proc.stderr


# ---------- top-io.json contract violations ----------


def test_fail_loud_missing_top_io(tmp_path):
    proc = _run(_wd(tmp_path, [], write_io=False), check=False)
    assert proc.returncode != 0 and "top-io.json" in proc.stderr


def test_fail_loud_empty_top_io(tmp_path):
    proc = _run(_wd(tmp_path, []), check=False)
    assert proc.returncode != 0 and "top-io.json" in proc.stderr


def test_fail_loud_invalid_role(tmp_path):
    bad = [{**_CLK_PORT, "role": "bogus"}]
    proc = _run(_wd(tmp_path, bad), check=False)
    assert proc.returncode != 0 and "role" in proc.stderr


def test_fail_loud_invalid_direction(tmp_path):
    bad = [{**_CLK_PORT, "direction": ""}]
    proc = _run(_wd(tmp_path, bad), check=False)
    assert proc.returncode != 0 and "direction" in proc.stderr


def test_fail_loud_reset_missing_kind(tmp_path):
    # if role == reset then reset_polarity + reset_kind — in the schema, not in Python.
    bad = [_CLK_PORT, _port("rst_n", "input", "reset", reset_polarity=0)]
    proc = _run(_wd(tmp_path, bad), check=False)
    assert proc.returncode != 0 and "reset_kind" in proc.stderr


def test_fail_loud_reset_invalid_polarity(tmp_path):
    bad = [
        _CLK_PORT,
        _port("rst_n", "input", "reset", reset_polarity=2, reset_kind="async"),
    ]
    proc = _run(_wd(tmp_path, bad), check=False)
    assert proc.returncode != 0 and "reset_polarity" in proc.stderr


def test_fail_loud_string_width(tmp_path):
    bad = [{**_CLK_PORT, "width": "1"}]
    proc = _run(_wd(tmp_path, bad), check=False)
    assert proc.returncode != 0 and "width" in proc.stderr


def test_fail_loud_misspelled_port_key(tmp_path):
    bad = [{**_CLK_PORT, "clock_domian": "clk"}]
    proc = _run(_wd(tmp_path, bad), check=False)
    assert proc.returncode != 0 and "clock_domian" in proc.stderr


# ---------- emitters ----------


def test_data_port_on_generated_clock_deferred(tmp_path):
    # A data port whose clock_domain is a GENERATED clock is deferred to RTL
    # (create_generated_clock pin not yet known). Both emitters skip it by design.
    ports = [_CLK_PORT, _port("pgen", "input", "data", domain="clk_div2", width=8)]
    clocks = [
        _clk("clk", 10.0),
        _clk("clk_div2", 20.0, "synchronous-related", generated=True),
    ]
    proc = _run(_wd(tmp_path, ports, clocks), check=False)
    assert proc.returncode == 0
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {pgen}" not in sgdc


def test_multi_domain_abstract_port_grouping(tmp_path):
    # driver-domain association: each data port groups under its OWN clock_domain.
    ports = [
        _CLK_PORT,
        _port("clk2", "input", "clock", domain="clk2"),
        _port("a", "input", "data", width=8),
        _port("b", "input", "data", domain="clk2", width=8),
    ]
    clocks = [_clk("clk", 10.0), _clk("clk2", 20.0, "async", role="second")]
    _run(_wd(tmp_path, ports, clocks))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {a} -clock clk" in sgdc
    assert "abstract_port -ports {b} -clock clk2" in sgdc


def test_input_only_module(tmp_path):
    ports = [_CLK_PORT, _port("din", "input", "data", width=8)]
    summary = json.loads(_run(_wd(tmp_path, ports)).stdout)
    assert summary["data_ports"] == 1
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_input_delay" in sdc and "set_output_delay" not in sdc


def test_output_only_module(tmp_path):
    ports = [_CLK_PORT, _port("dout", "output", "data", width=8)]
    _run(_wd(tmp_path, ports))
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_output_delay" in sdc and "set_input_delay" not in sdc


def test_no_data_port_module(tmp_path):
    ports = [
        _CLK_PORT,
        _port("rst_n", "input", "reset", reset_polarity=0, reset_kind="async"),
    ]
    summary = json.loads(_run(_wd(tmp_path, ports)).stdout)
    assert summary["data_ports"] == 0 and summary["resets"] == 1
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_input_delay" not in sdc and "set_output_delay" not in sdc


def test_short_named_data_port_on_generated_clock_deferred(tmp_path):
    # The generated-clock deferral applies regardless of name length.
    ports = [_CLK_PORT, _port("d", "input", "data", domain="clk_div2", width=8)]
    clocks = [
        _clk("clk", 10.0),
        _clk("clk_div2", 20.0, "synchronous-related", generated=True),
    ]
    proc = _run(_wd(tmp_path, ports, clocks), check=False)
    assert proc.returncode == 0
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {d}" not in sgdc


def test_sgdc_emits_async_clock_groups(tmp_path):
    # A primary + an async clock must produce a clock -domain declaration in the SGDC
    # too, not just set_clock_groups in the SDC. SpyGlass's SGDC parser rejects
    # set_clock_groups as an unknown command (confirmed on SpyGlass_vL-2016.06) — the
    # SGDC-native equivalent is `clock -domain <D>`, one shared domain per sync/primary
    # group, a distinct one per async clock.
    ports = [
        _CLK_PORT,
        _port("clk_io", "input", "clock", domain="clk_io"),
        _port("din", "input", "data", width=8),
    ]
    clocks = [
        _clk("clk", 10.0),
        _clk("clk_io", 20.0, "async", role="io clock"),
    ]
    _run(_wd(tmp_path, ports, clocks))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "set_clock_groups" not in sgdc
    assert "clock -name clk -period 10.0 -edge {0 5.0} -domain sync" in sgdc
    assert "clock -name clk_io -period 20.0 -edge {0 10.0} -domain clk_io" in sgdc


def test_sgdc_domain_label_collision_fails_loudly():
    # Guard: an async clock literally named "sync" would be assigned -domain sync and
    # silently merged into the synchronous group — a false-negative CDC hole. Must fail.
    clocks = [_clk("clk", 10.0), _clk("sync", 20.0, "async")]
    with pytest.raises(SystemExit):
        constraints._sgdc_clock_domains(clocks)


def test_sdc_sgdc_async_declaration_agrees_by_construction():
    # Both emitters render the SAME _clock_partition, so their async declarations agree
    # by construction. Asserted against the two functions, not by re-parsing their output.
    ports = [_port("din", "input", "data", width=8)]
    for clocks in (
        [_clk("clk", 10.0)],  # no async clock
        [_clk("clk", 10.0), _clk("clk_io", 20.0, "async")],  # async present
    ):
        sdc = constraints.generate_sdc("m", clocks, ports)
        sgdc = constraints.generate_sgdc("m", clocks, ports)
        sdc_async = "set_clock_groups" in sdc
        sgdc_async = any(
            ln.startswith("clock -name ") and "-domain" in ln.split()
            for ln in sgdc.splitlines()
        )
        assert sdc_async == sgdc_async
        # …and both equal the one partition they share.
        assert sdc_async == bool(constraints._clock_partition(clocks)[1])


def test_clock_named_like_domain_flag_not_spurious_fail(tmp_path):
    # A single sync clock literally named 'x-domain' (no async clocks) must not trip the
    # SDC/SGDC async-parity assertion (a bare '-domain' substring match would).
    ports = [
        _port("xd_clk", "input", "clock", domain="x-domain"),
        _port("din", "input", "data", domain="x-domain", width=8),
    ]
    clocks = [_clk("x-domain", 10.0, role="primary clock")]
    proc = _run(_wd(tmp_path, ports, clocks), check=False)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


# ── shapes the one-clock corpus never reached ────────────────────────────────────────────
def _io(name, direction, domain, role="data", width=1, **kw):
    r = {
        "name": name,
        "direction": direction,
        "width": width,
        "clock_domain": domain,
        "interface_group": "g",
        "role": role,
    }
    if role == "reset":
        r.setdefault("reset_polarity", 0)
        r.setdefault("reset_kind", "async")
    r.update(kw)
    return r


def test_inout_port_gets_both_delays():
    """`inout` is a legal `direction`, and the branch tested only the two unidirectional
    values — so a bidirectional pin came out of the SDC with no delay at all, which reads to
    dc_shell as a path with slack to spare."""
    clocks = [
        {
            "name": "clk",
            "period_ns": 10.0,
            "relationship": "primary",
            "generated": False,
        }
    ]
    ports = [
        _io("clk", "input", "clk", "clock"),
        _io("rst_n", "input", "clk", "reset"),
        _io("sda", "inout", "clk"),
    ]
    sdc = constraints.generate_sdc("dut", clocks, ports)
    assert "set_input_delay  3.0 -clock clk [get_ports {sda}]" in sdc
    assert "set_output_delay 3.0 -clock clk [get_ports {sda}]" in sdc


def test_generated_clock_domain_is_named_not_dropped():
    """A data port whose domain is a generated clock cannot be delayed here — synthesis
    writes create_generated_clock from rtl-design's pin. Skipping it silently left the port
    unconstrained in both files with nothing saying so."""
    clocks = [
        {
            "name": "clk",
            "period_ns": 10.0,
            "relationship": "primary",
            "generated": False,
        },
        {
            "name": "clk_div2",
            "period_ns": 20.0,
            "relationship": "synchronous-related",
            "generated": True,
        },
    ]
    ports = [
        _io("clk", "input", "clk", "clock"),
        _io("rst_n", "input", "clk", "reset"),
        _io("slow_out", "output", "clk_div2", width=8),
        _io("fast_in", "input", "clk", width=8),
    ]
    sdc = constraints.generate_sdc("dut", clocks, ports)
    assert "set_output_delay" not in sdc.replace("# set_output_delay", "")
    assert "slow_out: deferred" in sdc
    assert "set_input_delay  3.0 -clock clk [get_ports {fast_in}]" in sdc

    sgdc = constraints.generate_sgdc("dut", clocks, ports)
    assert "abstract_port -ports {fast_in} -clock clk" in sgdc
    assert "abstract_port deferred for {slow_out}" in sgdc


def test_every_data_port_is_accounted_for_in_the_sdc():
    """The property the shapes are really checking: no data port leaves the emitter without
    either a delay or a named deferral."""
    clocks = [
        {
            "name": "clk",
            "period_ns": 4.0,
            "relationship": "primary",
            "generated": False,
        },
        {
            "name": "clk_b",
            "period_ns": 6.0,
            "relationship": "async",
            "generated": False,
        },
        {
            "name": "clk_gen",
            "period_ns": 8.0,
            "relationship": "async",
            "generated": True,
        },
    ]
    ports = [
        _io("clk", "input", "clk", "clock"),
        _io("clk_b", "input", "clk_b", "clock"),
        _io("rst_n", "input", "clk", "reset"),
        _io("a", "input", "clk", width=4),
        _io("b", "output", "clk_b", width=4),
        _io("c", "inout", "clk"),
        _io("d", "output", "clk_gen", width=2),
    ]
    sdc = constraints.generate_sdc("dut", clocks, ports)
    for name in ("a", "b", "c", "d"):
        assert re.search(
            rf"(set_(in|out)put_delay .*\b{name}\b|# set_\w+_delay {name}:)", sdc
        ), f"{name} left the SDC with neither a delay nor a named deferral"
