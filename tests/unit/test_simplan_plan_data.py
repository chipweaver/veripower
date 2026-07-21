"""Tests for the simplan derive-plan-data verb — extracts the derived universe
(features, interfaces, clocks, scenarios, check_hints) from a spec workdir into
plan-data.json."""

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

## §5 Verification Hints (9 columns required)

| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |
|---------|---------------|----------------------|------------------------------|------------------|------------|---------------|---------|---------------|
| CHK-00 | F-00 | write reg | reg[addr] <= wdata | L12 | rdata | reg[addr]=wdata | 1 | 0 |
"""


def _workdir(tmp_path):
    (tmp_path / "design.md").write_text(DESIGN_MD)
    (tmp_path / "core.md").write_text(CHILD_MD)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "core", "doc": "core.md"}]})
    )
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


def test_clock_relationship_carried(tmp_path):
    pd = _plan_data(_workdir(tmp_path))
    assert pd["clocks"][0]["relationship"] == "primary"


def test_verbatim_extracted_risk_and_anchor_absent(tmp_path):
    pd = _plan_data(_workdir(tmp_path))
    h = pd["check_hints"][0]
    assert h["implementation_detail_verbatim"] == "reg[addr] <= wdata"
    assert h["implementation_detail"] == "write reg"
    assert "risk" not in h
    assert "brainstorm_anchor" not in h


def test_escaped_pipe_in_verbatim_cell_does_not_shift_columns(tmp_path):
    # Reproduces the wrom.md §5 corruption: a §5 ImplementationDetailVerbatim cell
    # legitimately quotes an interface-table row whose '|' separators are markdown-
    # escaped as '\|'. The parser must split on UNescaped '|' only (and unescape the
    # cell), else the verbatim cell over-splits and every column after it shifts right.
    child = (
        "# core\n\n## §5 Verification Hints (9 columns required)\n\n"
        "| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| CHK-P | F-00 | bank sel | `sel \\| in \\| 3 \\| bank select` | L99 | obs_sig | sel rule | comb | none |\n"
    )
    (tmp_path / "design.md").write_text(DESIGN_MD)
    (tmp_path / "core.md").write_text(child)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "core", "doc": "core.md"}]})
    )
    h = next(x for x in _plan_data(tmp_path)["check_hints"] if x["check_id"] == "CHK-P")
    assert h["implementation_detail"] == "bank sel"
    assert h["implementation_detail_verbatim"] == "`sel | in | 3 | bank select`"
    assert h["observable"] == "obs_sig"
    assert h["reference_rule"] == "sel rule"
    assert h["latency"] == "comb"
    assert h["reset_behavior"] == "none"


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


def test_derive_missing_features_table_fails_loud(tmp_path):
    # design.md present but no §1.3 Feature Table → ValueError, non-zero, no plan-data.json (D5).
    # A valid child is supplied so load_check_hints passes and load_features is the failure.
    (tmp_path / "design.md").write_text(
        "# m\n\n## 1. Module Overview\n\nno feature table here\n"
    )
    (tmp_path / "core.md").write_text(CHILD_MD)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "core", "doc": "core.md"}]})
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "1.3" in proc.stderr or "Feature Table" in proc.stderr
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
    # A1: two §5 rows share a check_id → by_id / check_ids would collapse them (covering
    # one "covers both", leaving the second silently unverified). Must fail loud.
    child = (
        "# core\n\n## §5 Verification Hints (9 columns required)\n\n"
        "| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| CHK-00 | F-00 | a | v1 | L1 | o1 | r1 | 1 | 0 |\n"
        "| CHK-00 | F-00 | b | v2 | L2 | o2 | r2 | 2 | 0 |\n"
    )
    (tmp_path / "design.md").write_text(DESIGN_MD)
    (tmp_path / "core.md").write_text(child)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "core", "doc": "core.md"}]})
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "duplicate check_id" in proc.stderr and "CHK-00" in proc.stderr
    assert not (tmp_path / "plan-data.json").exists()


def test_derive_misnamed_check_id_header_fails_loud(tmp_path):
    # A2: a §5 table whose Check-ID header is hyphenated (normalize_header does not strip
    # hyphens) maps to zero hints, silently dropping the child's entire hint set from the
    # coverage gate. With a §5 table PRESENT but Check ID unmapped, fail loud.
    child = (
        "# core\n\n## §5 Verification Hints (9 columns required)\n\n"
        "| Check-ID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| CHK-00 | F-00 | a | v1 | L1 | o1 | r1 | 1 | 0 |\n"
    )
    (tmp_path / "design.md").write_text(DESIGN_MD)
    (tmp_path / "core.md").write_text(child)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "core", "doc": "core.md"}]})
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "Check ID column" in proc.stderr and "core" in proc.stderr
    assert not (tmp_path / "plan-data.json").exists()


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
