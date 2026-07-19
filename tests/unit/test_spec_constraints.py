# tests/unit/test_spec_constraints.py
import json
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


def _design(io_rows, clk_rows):
    return (
        "# m Design\n\n#### 1.4.1 Top-Level IO\n\n"
        "| Signal | Direction | Width | Clock Domain | Interface Group | Protocol | Role | ResetPolarity | ResetKind |\n"
        "|---|---|---|---|---|---|---|---|---|\n" + io_rows + "\n"
        "### 1.6 Clocks and Frequencies\n\n"
        "| Clock Name | Nominal Frequency (MHz) | SDC Period (ns) | Relationship | Generated | Role |\n"
        "|---|---|---|---|---|---|\n" + clk_rows + "\n"
    )


def _wd(tmp_path, design):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "m",
                "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
            }
        )
    )
    (tmp_path / "design.md").write_text(design)
    return tmp_path


def test_core_clocks_and_io_delays(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n"
        "| dout | output | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    summary = json.loads(_run(_wd(tmp_path, design)).stdout)
    assert summary == {"top": "m", "clocks": 1, "data_ports": 2, "resets": 0}
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "create_clock -name clk -period 10.0 [get_ports clk]" in sdc
    assert "set_input_delay  3.0 -clock clk [get_ports {din}]" in sdc
    assert "set_output_delay 3.0 -clock clk [get_ports {dout}]" in sdc
    assert "clock -name clk -period 10.0 -edge {0 5.0}" in sgdc
    assert "abstract_port -ports {din dout} -clock clk" in sgdc
    # data/clock split exact via Role: clk gets no IO delay
    assert "[get_ports {clk}]" not in sdc


def test_async_reset_emits_async_flag(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst_n | input | 1 | clk | reset | - | reset | 0 | async |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    summary = json.loads(_run(_wd(tmp_path, design)).stdout)
    assert summary["resets"] == 1
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name rst_n -value 0 -async" in sgdc
    assert "abstract_port -ports rst_n -clock clk -reset rst_n" in sgdc


def test_sync_reset_drops_async_flag(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst | input | 1 | clk | reset | - | reset | 1 | sync |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    _run(_wd(tmp_path, design))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name rst -value 1\n" in sgdc  # no -async
    assert "-async" not in sgdc.split("reset -name rst")[1].split("\n")[0]


def test_no_reset_ports_emits_no_reset_section(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    _run(_wd(tmp_path, design))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "reset -name" not in sgdc


def test_async_clock_groups(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| clk_io | input | 1 | clk_io | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_io | 50 | 20.0 | async | no | io clock |\n",
    )
    _run(_wd(tmp_path, design))
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_clock_groups -asynchronous" in sdc
    assert "-group [get_clocks {clk}]" in sdc
    assert "-group [get_clocks clk_io]" in sdc


def test_generated_clock_skips_create_clock(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_div2 | 50 | 20.0 | synchronous-related | yes | divider out |\n",
    )
    json.loads(_run(_wd(tmp_path, design)).stdout)
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


def test_fail_loud_empty_clock_table(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n", ""
    )  # no clock rows
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "1.6" in proc.stderr


def test_fail_loud_invalid_role(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | bogus | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "Role" in proc.stderr


def test_fail_loud_reset_missing_kind(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst_n | input | 1 | clk | reset | - | reset | 0 | |\n"  # no ResetKind
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "ResetKind" in proc.stderr


def test_fail_loud_reset_empty_domain(tmp_path):
    # S2: a reset port with a blank Clock Domain would emit `abstract_port ... -clock `
    # (empty -clock token, invalid SGDC); the coverage gate skips empty domains, so
    # derive-constraints must fail loud — mirroring how reset polarity/kind are enforced.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst_n | input | 1 |  | reset | - | reset | 0 | async |\n"  # blank Clock Domain
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "Clock Domain" in proc.stderr


def test_fail_loud_invalid_relationship(tmp_path):
    # S3: an invalid/misspelled Relationship must fail loud, not silently fall into the
    # synchronous group (which would drop a needed set_clock_groups -asynchronous).
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | related | no | primary clock |\n",  # 'related' invalid
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "Relationship" in proc.stderr


def test_data_port_on_generated_clock_deferred(tmp_path):
    # A data port whose Clock Domain is a GENERATED clock is deferred to RTL
    # (create_generated_clock pin not yet known). generate_sdc/generate_sgdc skip it
    # by design, so the self-check mirrors that skip — it must NOT fail-loud demanding
    # an abstract_port the generators intentionally did not emit. Valid input → exit 0,
    # and no abstract_port is emitted for the deferred port.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| pgen | input | 8 | clk_div2 | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_div2 | 50 | 20.0 | synchronous-related | yes | divider out |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode == 0
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {pgen}" not in sgdc


def test_multi_domain_abstract_port_grouping(tmp_path):
    # driver-domain association: each data port groups under its OWN Clock Domain.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| clk2 | input | 1 | clk2 | clk | - | clock | - | - |\n"
        "| a | input | 8 | clk | cfg | APB3 | data | - | - |\n"
        "| b | input | 8 | clk2 | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk2 | 50 | 20.0 | async | no | second clock |\n",
    )
    _run(_wd(tmp_path, design))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {a} -clock clk" in sgdc
    assert "abstract_port -ports {b} -clock clk2" in sgdc


def test_input_only_module(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    summary = json.loads(_run(_wd(tmp_path, design)).stdout)
    assert summary["data_ports"] == 1
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_input_delay" in sdc and "set_output_delay" not in sdc


def test_output_only_module(tmp_path):
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| dout | output | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    _run(_wd(tmp_path, design))
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_output_delay" in sdc and "set_input_delay" not in sdc


def test_no_data_port_module(tmp_path):
    # clock + reset only, no data ports → valid output, no false requirement.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| rst_n | input | 1 | clk | reset | - | reset | 0 | async |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    summary = json.loads(_run(_wd(tmp_path, design)).stdout)
    assert summary["data_ports"] == 0 and summary["resets"] == 1
    sdc = (tmp_path / "constraints" / "m.sdc").read_text()
    assert "set_input_delay" not in sdc and "set_output_delay" not in sdc


def test_short_named_data_port_on_generated_clock_deferred(tmp_path):
    # The generated-clock deferral applies regardless of signal-name length: a short
    # name 'd' on a generated clock is skipped (deferred to RTL), not fail-louded.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| d | input | 8 | clk_div2 | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_div2 | 50 | 20.0 | synchronous-related | yes | divider out |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode == 0
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "abstract_port -ports {d}" not in sgdc


def test_sgdc_emits_async_clock_groups(tmp_path):
    # F1: a primary + an async clock must produce a clock -domain declaration in the SGDC too, not
    # just set_clock_groups in the SDC. SpyGlass's SGDC parser rejects set_clock_groups as
    # an unknown command (confirmed on SpyGlass_vL-2016.06, Task 2 of the F1 plan) — the
    # SGDC-native equivalent is `clock -domain <D>`, one shared domain per sync/primary
    # group, a distinct domain per async clock.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| clk_io | input | 1 | clk_io | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n",
        "| clk | 100 | 10.0 | primary | no | primary clock |\n"
        "| clk_io | 50 | 20.0 | async | no | io clock |\n",
    )
    _run(_wd(tmp_path, design))
    sgdc = (tmp_path / "constraints" / "m.sgdc").read_text()
    assert "set_clock_groups" not in sgdc
    assert "clock -name clk -period 10.0 -edge {0 5.0} -domain sync" in sgdc
    assert "clock -name clk_io -period 20.0 -edge {0 10.0} -domain clk_io" in sgdc


def test_sgdc_domain_label_collision_fails_loudly():
    # F1 guard: an async clock literally named "sync" would be assigned -domain sync and
    # silently merged into the synchronous group — a false-negative CDC hole. Must fail.
    clocks = [
        {"name": "clk", "period": 10.0, "relationship": "primary", "generated": False},
        {"name": "sync", "period": 20.0, "relationship": "async", "generated": False},
    ]
    with pytest.raises(SystemExit):
        constraints._sgdc_clock_domains(clocks)


def test_self_check_flags_clock_group_divergence():
    # F1 backstop: SDC (set_clock_groups) and SGDC (-domain) must agree on whether an
    # async clock declaration is present.
    sdc = "set_clock_groups -asynchronous -group [get_clocks {clk}] -group [get_clocks clk_io]\n"
    sgdc_ok = (
        "current_design m\nclock -name clk -period 10.0 -edge {0 5.0} -domain sync\n"
    )
    sgdc_bad = "current_design m\n"  # domain dropped — the divergence F1 fixes
    constraints._self_check("m", [], [], sdc, sgdc_ok)  # no raise
    with pytest.raises(SystemExit):
        constraints._self_check("m", [], [], sdc, sgdc_bad)


# ---------- F1: misnamed / empty §1.4.1 Signal column ----------


def test_fail_loud_misnamed_signal_column(tmp_path):
    # §1.4.1 with 'Port' instead of the canonical 'Signal' must fail loud, not silently
    # yield zero ports and IO-less constraints (the ports.py-class drift defect).
    design = (
        "# m Design\n\n#### 1.4.1 Top-Level IO\n\n"
        "| Port | Direction | Width | Clock Domain | Interface Group | Protocol | Role | ResetPolarity | ResetKind |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din | input | 8 | clk | cfg | APB3 | data | - | - |\n\n"
        "### 1.6 Clocks and Frequencies\n\n"
        "| Clock Name | Nominal Frequency (MHz) | SDC Period (ns) | Relationship | Generated | Role |\n"
        "|---|---|---|---|---|---|\n"
        "| clk | 100 | 10.0 | primary | no | primary clock |\n\n"
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "Signal" in proc.stderr


# ---------- F2: data port with blank / invalid Direction ----------


def test_fail_loud_data_port_blank_direction(tmp_path):
    # A data-role port silently dropped from the SDC (no set_input/output_delay) when its
    # Direction is blank/invalid. Must fail loud instead.
    design = _design(
        "| clk | input | 1 | clk | clk | - | clock | - | - |\n"
        "| din |  | 8 | clk | cfg | APB3 | data | - | - |\n",  # blank Direction
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode != 0 and "Direction" in proc.stderr


# ---------- F3: clock named like the '-domain' flag must not spuriously fail ----------


def test_clock_named_like_domain_flag_not_spurious_fail(tmp_path):
    # A single sync clock literally named 'x-domain' (no async clocks) must NOT trip the
    # SDC/SGDC async-parity self-check; the old bare '-domain' substring matched the
    # 'x-domain' inside `clock -name x-domain`.
    design = _design(
        "| xd_clk | input | 1 | x-domain | clk | - | clock | - | - |\n"
        "| din | input | 8 | x-domain | cfg | APB3 | data | - | - |\n",
        "| x-domain | 100 | 10.0 | primary | no | primary clock |\n",
    )
    proc = _run(_wd(tmp_path, design), check=False)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def test_ports_column_guard_uses_header_not_ragged_row0():
    # F5-consistency: the §1.4.1 column guard must check the declared HEADER, not the first
    # data row. A complete header with a ragged first data row must NOT false-report a
    # missing canonical column (it fails, if at all, with the accurate per-row reason).
    design = _design(
        "| din | input | 8 |\n",  # ragged: 3 cells under a 9-column header
        "| clk | 100 | 10.0 | primary | no | primary clock |\n",
    )
    with pytest.raises(SystemExit) as e:
        constraints._ports(design)
    assert "missing canonical column" not in str(e.value.code)
