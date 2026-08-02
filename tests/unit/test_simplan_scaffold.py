"""Tests for the simplan check-scaffold verb — gate: structural (jsonschema) + semantic cross-ref + coverage."""

import copy
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-plan/scripts/simplan/__main__.py"

# Canonical, post-materialize, fully-valid scaffold (agents carry materialize-injected
# interface/transaction). Built from the SKILL contract, NOT from any legacy disk artifact.
GOOD = {
    "module": "m",
    "top": "m_top",
    "agents": [
        {
            "name": "drv",
            "mode": "active",
            "interface_groups": ["cfg"],
        },
        {
            "name": "obs",
            "mode": "passive",
            "interface_groups": ["stat"],
        },
    ],
    "sequences": [{"name": "smoke", "agent": "drv", "desc": "smoke"}],
    "tests": [
        {
            "name": "t_smoke",
            "feature": "F1",
            "test_id": "T1",
            "suites": ["smoke", "regress"],
            "feature_name": "Register write path",
            "seqs": ["smoke"],
        }
    ],
    "rm": {"name": "m_rm", "inports": ["drv"]},
    "scoreboard": {"name": "m_sb", "observer": "obs"},
    "testpoints": [
        {
            "id": "TP-1",
            "intent": "drive TP-1 and observe it",
            "bins": ["a"],
            "covers": ["CHK-0"],
            "inlined_check_hints": [
                {"check_id": "CHK-0", "implementation_detail": "x"}
            ],
        }
    ],
    "power_scenarios": [
        {
            "id": "S1",
            "sequence_ref": "smoke",
            "corner_intent": "SS/125C",
        }
    ],
}


_TOP_IO = [
    {
        "name": "clk",
        "direction": "input",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "cfg",
        "role": "clock",
    },
    {
        "name": "rst_n",
        "direction": "input",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "cfg",
        "role": "reset",
        "reset_polarity": 0,
        "reset_kind": "async",
    },
    {
        "name": "wdata",
        "direction": "input",
        "width": 32,
        "clock_domain": "clk",
        "interface_group": "cfg",
        "role": "data",
    },
    {
        "name": "rdata",
        "direction": "output",
        "width": 32,
        "clock_domain": "clk",
        "interface_group": "stat",
        "role": "data",
    },
]


def _spec(tmp_path, hints=None, top_io=None):
    """tmp_path doubles as the spec workdir: manifest + check-hints/ + top-io.json."""
    (tmp_path / "top-io.json").write_text(
        json.dumps(_TOP_IO if top_io is None else top_io)
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "c", "doc": "c.md"}]})
    )
    hd = tmp_path / "check-hints"
    hd.mkdir(exist_ok=True)
    (hd / "c.json").write_text(
        json.dumps([{"check_id": "CHK-0"}] if hints is None else hints)
    )
    return tmp_path


def _split(tmp_path, scaffold):
    """Project one in-memory plan dict onto the three on-disk sidecars the gate reads.
    The tests keep authoring one dict because that is the shape the cross-array checks are
    about; the split is a property of the files, not of the checks."""
    doc = dict(scaffold)
    for name, key in (
        ("sequences.json", "sequences"),
        ("power-scenarios.json", "power_scenarios"),
    ):
        (tmp_path / name).write_text(json.dumps(doc.pop(key, [])))
    (tmp_path / "tb-scaffold.json").write_text(json.dumps(doc))


def _run(tmp_path, scaffold, check=True, hints=None, top_io=None):
    _split(tmp_path, scaffold)
    _spec(tmp_path, hints, top_io)
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "check-scaffold",
            "--plan",
            str(tmp_path),
            "--spec",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def test_good_scaffold_passes(tmp_path):
    proc = _run(tmp_path, GOOD)
    assert proc.returncode == 0 and "OK" in proc.stdout


def test_malformed_scaffold_json_fails_loud(tmp_path):
    # A6: a JSON syntax error in a sidecar must fail loud with a fix-oriented message,
    # not a raw traceback.
    _split(tmp_path, GOOD)
    (tmp_path / "tb-scaffold.json").write_text("{ oops ]")
    _spec(tmp_path, [])
    proc = subprocess.run(
        [
            "python3",
            str(MAIN),
            "check-scaffold",
            "--plan",
            str(tmp_path),
            "--spec",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "not valid JSON" in proc.stderr and "Traceback" not in proc.stderr


def test_injected_interface_transaction_tolerated(tmp_path):
    # GOOD already carries materialize-injected interface/transaction. addP:false must not reject them.
    assert _run(tmp_path, GOOD).returncode == 0


# ---- structural ----
def test_observer_list_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["scoreboard"]["observer"] = ["a", "b"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "observer" in proc.stderr


def test_inports_string_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["rm"]["inports"] = "drv"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "inports" in proc.stderr


def test_seqs_string_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["tests"][0]["seqs"] = "smoke"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "seqs" in proc.stderr


def test_mode_non_enum_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"][0]["mode"] = "master"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "mode" in proc.stderr


def test_mode_missing_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    del s["agents"][0]["mode"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "mode" in proc.stderr


def test_missing_interface_groups_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    del s["agents"][0]["interface_groups"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "interface_groups" in proc.stderr


def test_agent_extra_key_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"][0]["drive_signals"] = ["wdata"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0  # additionalProperties:false on agents[]


# ---- boundary: the agents must partition top-io.json's data ports ----
def test_unclaimed_data_port_group_fails(tmp_path):
    """simulation binds the DUT by walking the ports, so a group no agent claims has nothing
    to bind to. Held here because the plan passes a human approval gate first."""
    s = copy.deepcopy(GOOD)
    s["agents"] = [a for a in s["agents"] if a["name"] != "obs"]
    s["scoreboard"]["observer"] = "drv"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0
    assert "stat" in proc.stderr and "no agent claims" in proc.stderr


def test_group_claimed_twice_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"][1]["interface_groups"] = ["cfg", "stat"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "claimed by both" in proc.stderr


def test_clock_and_reset_groups_need_no_agent(tmp_path):
    """clk/rst carry an interface_group like every other row, but the bench drives them, so
    a group holding only clock/reset is not one an agent has to claim."""
    top_io = [dict(p) for p in _TOP_IO]
    for p_ in top_io:
        if p_["role"] in ("clock", "reset"):
            p_["interface_group"] = "clkrst"
    assert _run(tmp_path, GOOD, top_io=top_io).returncode == 0


# ---- semantic ----
def test_observer_unknown_agent_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["scoreboard"]["observer"] = "nope"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "observer" in proc.stderr


def test_observer_omitted_single_agent_passes(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"] = [s["agents"][0]]  # single agent: drv
    s["sequences"] = [{"name": "smoke", "agent": "drv"}]
    s["rm"]["inports"] = ["drv"]
    del s["scoreboard"]["observer"]
    s["agents"][0]["interface_groups"] = ["cfg", "stat"]  # one agent, so it owns both
    assert _run(tmp_path, s).returncode == 0


def test_observer_omitted_multi_agent_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    del s["scoreboard"]["observer"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "observer" in proc.stderr  # option-c


def test_inports_unknown_agent_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["rm"]["inports"] = ["ghost"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "inports" in proc.stderr


def test_seqs_unknown_sequence_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["tests"][0]["seqs"] = ["ghost"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "seqs" in proc.stderr


def test_sequence_agent_unknown_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["sequences"][0]["agent"] = "ghost"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "agent" in proc.stderr


def test_sequence_without_agent_fails(tmp_path):
    # power-analysis's emit_power_tests builds m_<agent>_agent from it and hard-fails when
    # it is absent, so an entry omitting it must not clear this stage's gate.
    s = copy.deepcopy(GOOD)
    del s["sequences"][0]["agent"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "agent" in proc.stderr


def test_sequence_ref_unknown_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["power_scenarios"][0]["sequence_ref"] = "ghost"
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "sequence_ref" in proc.stderr


def test_sequence_ref_non_string_fails(tmp_path):
    # A non-string sequence_ref must fail structurally (clean message), not crash with a
    # TypeError in the semantic membership check (power_scenarios items are addP:true).
    s = copy.deepcopy(GOOD)
    s["power_scenarios"][0]["sequence_ref"] = ["smoke"]
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "sequence_ref" in proc.stderr


def test_duplicate_agent_name_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["agents"][1]["name"] = "drv"  # both agents now named "drv"
    s["scoreboard"]["observer"] = "drv"  # keep refs resolving so only the dup fires
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "duplicated" in proc.stderr


def test_skipped_checks_shape_validated(tmp_path):
    """skipped_checks[] entries require check_id + reason; a malformed entry fails structurally."""
    s = copy.deepcopy(GOOD)
    s["skipped_checks"] = [{"check_id": "CHK-9"}]  # missing 'reason'
    proc = _run(tmp_path, s, check=False)
    assert proc.returncode != 0 and "reason" in proc.stderr


# ---- coverage matrix ----
def test_coverage_uncovered_check_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["testpoints"] = [
        {
            "id": "TP-0",
            "intent": "drive TP-0 and observe it",
            "covers": ["CHK-00"],
            "inlined_check_hints": [
                {"check_id": "CHK-00", "implementation_detail": "x"}
            ],
        }
    ]
    proc = _run(
        tmp_path,
        s,
        check=False,
        hints=[{"check_id": "CHK-00"}, {"check_id": "CHK-01"}],
    )
    assert (
        proc.returncode != 0 and "uncovered" in proc.stderr and "CHK-01" in proc.stderr
    )


def test_coverage_skip_passes(tmp_path):
    s = copy.deepcopy(GOOD)
    s["testpoints"] = [
        {
            "id": "TP-0",
            "intent": "drive TP-0 and observe it",
            "covers": ["CHK-00"],
            "inlined_check_hints": [
                {"check_id": "CHK-00", "implementation_detail": "x"}
            ],
        }
    ]
    s["skipped_checks"] = [{"check_id": "CHK-01", "reason": "lint-only gate"}]
    proc = _run(
        tmp_path,
        s,
        hints=[{"check_id": "CHK-00"}, {"check_id": "CHK-01"}],
    )
    assert proc.returncode == 0


def test_coverage_dangling_covers_fails(tmp_path):
    s = copy.deepcopy(GOOD)
    s["testpoints"] = [
        {
            "id": "TP-0",
            "intent": "drive TP-0 and observe it",
            "covers": ["CHK-00", "CHK-99"],
            "inlined_check_hints": [
                {"check_id": "CHK-00", "implementation_detail": "x"}
            ],
        }
    ]
    proc = _run(tmp_path, s, check=False, hints=[{"check_id": "CHK-00"}])
    assert (
        proc.returncode != 0
        and "unknown check_id" in proc.stderr
        and "CHK-99" in proc.stderr
    )


def test_coverage_fully_covered_passes(tmp_path):
    s = copy.deepcopy(GOOD)
    s["testpoints"] = [
        {
            "id": "TP-0",
            "intent": "drive TP-0 and observe it",
            "covers": ["CHK-00", "CHK-01"],
            "inlined_check_hints": [
                {"check_id": "CHK-00", "implementation_detail": "x"},
                {"check_id": "CHK-01", "implementation_detail": "y"},
            ],
        }
    ]
    proc = _run(
        tmp_path,
        s,
        hints=[{"check_id": "CHK-00"}, {"check_id": "CHK-01"}],
    )
    assert proc.returncode == 0


# ── in-process: identity is the agent name itself + schema path ───────────────
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "simulation-plan" / "scripts"))
from simplan import scaffold as sc_mod  # noqa: E402


def test_agent_name_needs_no_unwrapping():
    # The producer gate and the consumer both resolve `observer` / `inports` by looking the
    # value up in agents[] verbatim — no transform to keep byte-identical across two skills.
    errs = sc_mod.semantic_errors(
        {
            "module": "m",
            "agents": [{"name": "m_wb_txn_agent"}],
            "sequences": [],
            "tests": [],
            "rm": {"inports": ["m_wb_txn_agent"]},
            "scoreboard": {"observer": "m_wb_txn_agent"},
            "testpoints": [],
            "power_scenarios": [],
        }
    )
    assert errs == []


def test_every_sidecar_schema_resolves():
    # the package is scripts/simplan/, so _REFERENCES needs one extra parent (SC6)
    from simplan import _plan

    for _, schema_name, _ in _plan._FILES:
        assert (_plan._REFERENCES / schema_name).is_file(), schema_name
