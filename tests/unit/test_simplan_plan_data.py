"""Tests for the simplan derive-plan-data verb — extracts interfaces, check_hints and
cross_module_wires from a spec workdir into plan-data.json."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-plan/scripts/simplan/__main__.py"

# ── DESIGN_MD / CHILD_MD : copy VERBATIM from the pre-consolidation derive-plan-data test
#    (lines 11–43). Reproduced here so the new file is self-contained. ──
DESIGN_MD = """# m Design Document (design.md)

## 1. Module Overview

### 1.3 Feature Table

| ID | Feature | Description |
|----|---------|-------------|
| F-00 | cfg | config write |

#### 1.4.1 Top-Level IO

| Signal | Direction | Width | Clock Domain | Interface Group | Protocol | Role | ResetPolarity | ResetKind |
|--------|-----------|-------|--------------|-----------------|----------|------|---------------|-----------|
| clk | input | 1 | clk | cfg | - | clock | - | - |
| rst_n | input | 1 | clk | cfg | - | reset | 0 | async |
| wdata | input | 32 | clk | cfg | - | data | - | - |

### 1.6 Clocks and Frequencies

| Clock Name | Nominal Frequency (MHz) | SDC Period (ns) | Relationship | Generated | Role |
|------------|-------------------------|-----------------|--------------|-----------|------|
| clk | 100 | 10.0 | primary | no | primary clock |
"""

CHILD_MD = """# core

## 1 Purpose

The register bank.
"""

CHECK_HINTS = [
    {
        "check_id": "CHK-00",
        "source_feature": "F-00",
        "implementation_detail": "write reg",
        "implementation_detail_verbatim": "reg[addr] <= wdata",
        "brainstorm_anchor": "L12",
        "observable": "rdata",
        "reference_rule": "reg[addr]=wdata",
        "latency": "1",
        "reset_behavior": "0",
    }
]


def _workdir(tmp_path, hints=None):
    (tmp_path / "design.md").write_text(DESIGN_MD)
    (tmp_path / "core.md").write_text(CHILD_MD)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "core", "doc": "core.md"}]})
    )
    hd = tmp_path / "check-hints"
    hd.mkdir(exist_ok=True)
    (hd / "core.json").write_text(json.dumps(CHECK_HINTS if hints is None else hints))
    return tmp_path


def _run(workdir, check=True):
    return subprocess.run(
        ["python3", str(MAIN), "derive-plan-data", "--workdir", str(workdir)],
        capture_output=True,
        text=True,
        check=check,
    )


def _plan_data(workdir):
    _run(workdir)
    return json.loads((workdir / "plan-data.json").read_text())


# ── relocated VERBATIM (bodies only; _run now returns a CompletedProcess) ──
def test_interface_role_carried(tmp_path):
    pd = _plan_data(_workdir(tmp_path))
    roles = {s["signal_name"]: s["role"] for s in pd["interfaces"]}
    assert roles == {"clk": "clock", "rst_n": "reset", "wdata": "data"}


def test_clocks_no_longer_derived(tmp_path):
    # Clocks are authored as Design/specification/clocks.json and read from there.
    # Asserting the key is ABSENT keeps a re-added markdown clock parser from passing.
    pd = _plan_data(_workdir(tmp_path))
    assert "clocks" not in pd


def test_hints_are_carried_verbatim_plus_a_child_tag(tmp_path):
    # The aggregate copies each authored entry as-is and adds `child`. Selecting which
    # fields reach the scaffold is materialize-scaffold's job, not this loader's.
    pd = _plan_data(_workdir(tmp_path))
    h = pd["check_hints"][0]
    assert h == {**CHECK_HINTS[0], "child": "core"}


def test_pipes_in_a_verbatim_value_need_no_escaping(tmp_path):
    # A verbatim value legitimately quotes an interface-table row whose separators are
    # pipes. Nothing escapes them and nothing shifts.
    hints = [
        {
            **CHECK_HINTS[0],
            "check_id": "CHK-P",
            "implementation_detail": "bank sel",
            "implementation_detail_verbatim": "`sel | in | 3 | bank select`",
            "observable": "obs_sig",
        }
    ]
    h = next(
        x
        for x in _plan_data(_workdir(tmp_path, hints))["check_hints"]
        if x["check_id"] == "CHK-P"
    )
    assert h["implementation_detail_verbatim"] == "`sel | in | 3 | bank select`"
    assert h["observable"] == "obs_sig"


def test_idempotent_no_authored_state(tmp_path):
    wd = _workdir(tmp_path)
    first = _plan_data(wd)
    second = _plan_data(wd)
    assert first == second


# ── net-new: fail-loud guards (spec §4 — enumerate fail-loud, not just happy path) ──
def test_derive_missing_design_md_fails_loud(tmp_path):
    # manifest present, design.md absent → sys.exit (D6)
    (tmp_path / "manifest.json").write_text(json.dumps({"module": "m", "children": []}))
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "design.md" in proc.stderr


def test_derive_no_parsable_section_fails_loud(tmp_path):
    # A design.md with none of the sections this verb parses must fail loud rather than
    # write a thin plan-data.json. §1.4.1 carries that guard: every module has top-level
    # IO, and its presence is gated upstream.
    wd = _workdir(tmp_path)  # valid manifest + child + check-hints
    (wd / "design.md").write_text("# m\n\n## 1. Module Overview\n\nno tables here\n")
    proc = _run(wd, check=False)
    assert proc.returncode != 0
    assert "1.4.1" in proc.stderr
    # S6: clean fail-loud, not a raw traceback (matches the missing-design.md line)
    assert (
        proc.stderr.startswith("derive-plan-data:") and "Traceback" not in proc.stderr
    )
    assert not (tmp_path / "plan-data.json").exists()


def test_derive_invalid_utf8_design_fails_loud(tmp_path):
    # C4: a decode error in a hand-authored spec must fail loud, not be papered over
    # with errors="ignore" (silently dropping bytes — e.g. an ID digit). The plan is
    # otherwise valid; only the stray 0xFF byte distinguishes drop-vs-fail.
    (tmp_path / "manifest.json").write_text(json.dumps({"module": "m", "children": []}))
    (tmp_path / "design.md").write_bytes(
        DESIGN_MD.encode("utf-8") + b"\n<!-- \xff -->\n"
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert (
        proc.stderr.startswith("derive-plan-data:") and "Traceback" not in proc.stderr
    )
    assert not (tmp_path / "plan-data.json").exists()


def test_derive_missing_manifest_fails_loud(tmp_path):
    # design.md present (valid §1.3), manifest.json absent → load_check_hints raises
    # FileNotFoundError BEFORE any write → non-zero, no plan-data.json (D8)
    (tmp_path / "design.md").write_text(DESIGN_MD)
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "manifest.json" in proc.stderr
    # S6: clean fail-loud, not a raw traceback (matches the missing-design.md line)
    assert (
        proc.stderr.startswith("derive-plan-data:") and "Traceback" not in proc.stderr
    )
    assert not (tmp_path / "plan-data.json").exists()


def test_derive_output_override_writes_requested_path(tmp_path):
    # --output redirects the write; default {workdir}/plan-data.json is NOT created (D9 — the
    # edge-capability + the net-new dispatcher --output wiring)
    wd = _workdir(tmp_path)
    out = tmp_path / "custom" / "pd.json"
    subprocess.run(
        [
            "python3",
            str(MAIN),
            "derive-plan-data",
            "--workdir",
            str(wd),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.is_file()
    assert json.loads(out.read_text())[
        "interfaces"
    ]  # real content at the override path
    assert not (wd / "plan-data.json").exists()


# ── net-new: input-hardening fail-loud guards (A1, A2, A3, A5) ──
def test_derive_duplicate_check_id_fails_loud(tmp_path):
    # Two entries sharing a check_id would collapse in by_id — one testpoint would appear
    # to cover both, leaving the second silently unverified. Uniqueness is global, which
    # is why the per-child files are aggregated before it is checked.
    dup = [CHECK_HINTS[0], {**CHECK_HINTS[0], "implementation_detail": "b"}]
    proc = _run(_workdir(tmp_path, dup), check=False)
    assert proc.returncode != 0
    assert "duplicate check_id" in proc.stderr and "CHK-00" in proc.stderr
    assert not (tmp_path / "plan-data.json").exists()


def test_derive_missing_child_hint_file_fails_loud(tmp_path):
    # A child in the manifest with no check-hints file would silently contribute nothing
    # to the coverage matrix.
    wd = _workdir(tmp_path)
    (wd / "check-hints" / "core.json").unlink()
    proc = _run(wd, check=False)
    assert proc.returncode != 0
    assert "check-hints/core.json" in proc.stderr
    assert not (wd / "plan-data.json").exists()


def test_derive_entry_without_check_id_fails_loud(tmp_path):
    bad = [{k: v for k, v in CHECK_HINTS[0].items() if k != "check_id"}]
    proc = _run(_workdir(tmp_path, bad), check=False)
    assert proc.returncode != 0 and "check_id" in proc.stderr


def test_derive_misnamed_signal_name_header_fails_loud(tmp_path):
    # A3: §1.4.1 table PRESENT but its Signal-Name header is mis-named → load_interfaces
    # would return [] and emit a thin plan-data.json. Must fail loud (mirrors load_features).
    wd = _workdir(tmp_path)
    (wd / "design.md").write_text(
        DESIGN_MD.replace("| Signal | Direction |", "| Sig | Direction |")
    )
    proc = _run(wd, check=False)
    assert proc.returncode != 0
    assert "Signal Name" in proc.stderr and "1.4.1" in proc.stderr
    assert not (wd / "plan-data.json").exists()


def test_derive_empty_or_malformed_children_fails_loud(tmp_path):
    # A5: children[] empty → clean sys.exit (not a bare KeyError / trivial zero-check pass);
    # a non-dict child in the list → TypeError backstop in run() (clean exit, no traceback).
    (tmp_path / "design.md").write_text(DESIGN_MD)
    (tmp_path / "manifest.json").write_text(json.dumps({"module": "m", "children": []}))
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "children" in proc.stderr and "Traceback" not in proc.stderr
    assert not (tmp_path / "plan-data.json").exists()
    # non-list/string child → TypeError caught by run()'s backstop tuple, clean exit
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": ["core"]})
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert (
        proc.stderr.startswith("derive-plan-data:") and "Traceback" not in proc.stderr
    )
