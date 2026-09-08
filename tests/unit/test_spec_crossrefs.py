"""check-crossrefs: the joins no single author of this stage's artifacts can see.

One question, unanswerable by any single author: does what one file wrote agree with the file
that owns it. Each test asserts on the violation an agent actually reads — where + what — not
on an internal key, because that sentence IS the interface. A sidecar's own shape is not tested
here (read-time, see test_spec_sidecar.py).
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"
sys.path.insert(0, str(ROOT / "skills/specification/scripts"))

_CLOCKS = [
    {"name": "clk", "io_delay_ns": 3.0, "period_ns": 10.0, "relationship": "primary"}
]
_ROWS = [
    {"id": "R-00", "verbatim": "y follows the reference model", "judge": "simulation"},
    {"id": "R-01", "verbatim": "ports are Verilog-2001", "judge": "rtl-design"},
    {
        "id": "R-02",
        "verbatim": "line coverage above 90%",
        "judge": "simulation",
        "target": {"dim": "coverage_line", "op": ">", "value": 90},
    },
]
_HINTS = [
    {
        "check_id": "CHK-0",
        "requirements": ["R-00"],
        "observable": "y",
        "reference_rule": "rm",
    }
]


def _port(name, direction, role, domain="clk", width=1, group="cfg"):
    return {
        "name": name,
        "direction": direction,
        "width": width,
        "clock_domain": domain,
        "interface_group": group,
        "role": role,
    }


_PORTS = [_port("clk", "input", "clock"), _port("din", "input", "data", width=8)]


def _workdir(tmp_path, clocks=None, rows=None, ports=None, hints=None):
    """A complete specification workdir, as it stands when check-crossrefs runs."""
    (tmp_path / "manifest.json").write_text(json.dumps({"module": "m"}))
    (tmp_path / "clocks.json").write_text(
        json.dumps(_CLOCKS if clocks is None else clocks)
    )
    (tmp_path / "requirements.json").write_text(
        json.dumps(_ROWS if rows is None else rows)
    )
    (tmp_path / "top-io.json").write_text(
        json.dumps(_PORTS if ports is None else ports)
    )
    (tmp_path / "check-hints.json").write_text(
        json.dumps(_HINTS if hints is None else hints)
    )
    return tmp_path


def _verdict(tmp_path, **kw):
    from spec import crossrefs

    return crossrefs.verdict(_workdir(tmp_path, **kw))


def _said(v, where, what_fragment):
    return any(
        x["where"] == where and what_fragment in x["what"] for x in v["violations"]
    )


def _run(workdir):
    return subprocess.run(
        ["python3", str(MAIN), "check-crossrefs", "--workdir", str(workdir)],
        capture_output=True,
        text=True,
    )


# ---------- clean ----------


def test_clean_workdir_passes(tmp_path):
    v = _verdict(tmp_path)
    assert v == {"status": "pass", "violations": []}


# ---------- the boundary's own clock domains ----------


def test_port_clock_domain_not_in_clocks_json(tmp_path):
    # A phantom domain renders `abstract_port -clock <phantom>` and hides a CDC path.
    ports = _PORTS + [_port("q", "output", "data", domain="ghost")]
    v = _verdict(tmp_path, ports=ports)
    assert _said(v, "top-io.json q", "'ghost' is not in clocks.json")


# ---------- hints against the ledger ----------


def test_hint_naming_a_row_the_ledger_lacks_is_reported(tmp_path):
    hints = [{**_HINTS[0], "requirements": ["R-99"]}]
    v = _verdict(tmp_path, hints=hints)
    assert _said(
        v, "check-hints.json CHK-0", "'R-99', which requirements.json does not have"
    )


def test_hint_naming_a_row_another_stage_judges_is_reported(tmp_path):
    # A hint for a row established elsewhere would turn it into a gating check the engineer
    # did not ask for.
    hints = [{**_HINTS[0], "requirements": ["R-01"]}]
    v = _verdict(tmp_path, hints=hints)
    assert _said(v, "check-hints.json CHK-0", "'R-01', which is not a simulation row")


def test_hint_naming_a_coverage_row_is_reported(tmp_path):
    # A row with a target is compared by simulation's own gate, not by a hint.
    hints = [{**_HINTS[0], "requirements": ["R-02"]}]
    v = _verdict(tmp_path, hints=hints)
    assert _said(v, "check-hints.json CHK-0", "'R-02', which is not a simulation row")


def test_simulation_row_no_hint_names_is_reported(tmp_path):
    # The orphan: nothing else asks whether every row simulation judges has an observation.
    rows = _ROWS + [
        {"id": "R-03", "verbatim": "busy falls with done", "judge": "simulation"}
    ]
    v = _verdict(tmp_path, rows=rows)
    assert _said(v, "requirements.json R-03", "no check-hints entry names it")


def test_a_row_two_hints_name_is_covered_once(tmp_path):
    hints = _HINTS + [{**_HINTS[0], "check_id": "CHK-1"}]
    v = _verdict(tmp_path, hints=hints)
    assert v["status"] == "pass", v


def test_duplicate_check_id_in_the_file_is_reported(tmp_path):
    # check_id is the coverage matrix's key, so a reused one makes one testpoint appear to
    # cover both and leaves the second silently unverified.
    v = _verdict(tmp_path, hints=_HINTS + _HINTS)
    assert _said(v, "check-hints.json CHK-0", "already used in this file")


# ---------- every disagreement, and the verb's contract ----------


def test_every_disagreement_is_reported_not_just_the_first(tmp_path):
    rows = _ROWS + [
        {"id": "R-03", "verbatim": "busy falls with done", "judge": "simulation"}
    ]
    ports = _PORTS + [_port("q", "output", "data", domain="ghost")]
    hints = [{**_HINTS[0], "requirements": ["R-99"]}]
    v = _verdict(tmp_path, rows=rows, ports=ports, hints=hints)
    wheres = {x["where"] for x in v["violations"]}
    assert wheres == {
        "check-hints.json CHK-0",
        "requirements.json R-00",
        "requirements.json R-03",
        "top-io.json q",
    }, v


def test_verb_prints_the_verdict_and_exits_zero(tmp_path):
    r = _run(_workdir(tmp_path))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"status": "pass", "violations": []}


def test_verb_exits_one_on_a_violation(tmp_path):
    wd = _workdir(tmp_path, hints=[{**_HINTS[0], "requirements": ["R-99"]}])
    r = _run(wd)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert json.loads(r.stdout)["status"] == "fail"


def test_verb_raises_on_a_malformed_sidecar(tmp_path):
    wd = _workdir(tmp_path)
    (wd / "check-hints.json").write_text(json.dumps([{"check_id": "CHK-0"}]))
    r = _run(wd)
    assert r.returncode != 0
    assert "check-hints.json" in r.stderr


def test_a_missing_input_names_the_file_and_is_routable(tmp_path):
    # Not BLOCKED: an unauthored hints file is fixed by re-dispatching the sub-Task that writes
    # it, which is what exit 1 means. The message has to name the file for that to be possible.
    wd = _workdir(tmp_path)
    (wd / "check-hints.json").unlink()
    r = _run(wd)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "check-hints.json" in r.stderr and "missing" in r.stderr
    assert r.stdout.strip() == ""
