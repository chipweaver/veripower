import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402
import rules  # noqa: E402
import store  # noqa: E402

TS = "2026-07-10T00:00:00.000000Z"


def fp(module, rel):
    return facts.fingerprint(Path(module) / rel)


def write_file(module, rel, text):
    """Write a file under the module root, taking the write bit back first: the kernel leaves
    the intent tree unwritable, and revising it is exactly `chmod u+w` then edit."""
    root = Path(module)
    p = root / rel
    intent = root / "intent"
    # The kernel leaves the intent tree unwritable; revising it is `chmod -R u+w intent`
    # then edit, which is what a test that changes the engineer's document is doing.
    if intent.exists() and str(p).startswith(str(intent)):
        for q in (intent, *intent.rglob("*")):
            if not q.is_symlink():
                q.chmod(q.stat().st_mode | 0o200)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_proof_valid_then_input_change_invalidates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "v1")
    write_file("m", "Design/specification/design.md", "d1")
    v = fp("m", "intent")
    store.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"intent": v},
            "params": {},
        },
        TS,
    )
    store.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "specification",
            "run": 1,
            "verdict": "pass",
            "outputs": {
                "Design/specification/design.md": fp(
                    "m", "Design/specification/design.md"
                )
            },
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"intent": v},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    evs = store.read_events("m")
    assert facts.proof_valid("m", evs, "specification")
    write_file("m", "intent/brainstorm.md", "v2-changed")  # input drifts
    assert not facts.proof_valid("m", evs, "specification")


def test_proof_invalid_when_own_output_handedited(tmp_path, monkeypatch):
    # Hand-editing the rule's own output invalidates its proof.
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "v1")
    dm = write_file("m", "Design/specification/design.md", "d1")
    v = fp("m", "intent")
    store.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"intent": v},
            "params": {},
        },
        TS,
    )
    store.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "specification",
            "run": 1,
            "verdict": "pass",
            "outputs": {
                "Design/specification/design.md": fp(
                    "m", "Design/specification/design.md"
                )
            },
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"intent": v},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    evs = store.read_events("m")
    assert facts.proof_valid("m", evs, "specification")
    dm.write_text("hand-edited")  # tamper own output
    assert not facts.proof_valid("m", evs, "specification")


def test_fail_verdict_is_not_valid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "v1")
    v = fp("m", "intent")
    store.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"intent": v},
            "params": {},
        },
        TS,
    )
    store.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "specification",
            "run": 1,
            "verdict": "fail",
            "outputs": {},
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "fail",
                    "inputs": {"intent": v},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    assert not facts.proof_valid("m", store.read_events("m"), "specification")


def test_hand_editing_canonical_result_json_invalidates_proof(tmp_path, monkeypatch):
    # The published result.json is fingerprinted like every other delivered output.
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "b1")
    rjrel = "Design/specification/result.json"
    write_file("m", rjrel, '{"status": "pass"}')
    bm = fp("m", "intent")
    rj = fp("m", rjrel)
    store.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "specification",
            "run": 1,
            "workdir": "w",
            "inputs": {"intent": bm},
            "params": {},
        },
        TS,
    )
    store.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "specification",
            "run": 1,
            "verdict": "pass",
            "outputs": {rjrel: rj},
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"intent": bm},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    assert facts.proof_valid("m", store.read_events("m"), "specification")
    write_file(
        "m", rjrel, '{"status": "pass", "coverage": "INFLATED"}'
    )  # 灌水: edit result.json
    assert not facts.proof_valid("m", store.read_events("m"), "specification")


def test_recorded_review_directory_changes_invalidate_the_conclusion(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "requirements")
    review = Path("m") / "Design/specification/spec-review"
    (review / "per-child").mkdir(parents=True)
    files = {"review.md": "holds", "notes.txt": "notes", "per-child/top.md": "top"}
    for rel, text in files.items():
        (review / rel).write_text(text)
    spec_run("m", 1)
    events = store.read_events("m")
    event = events[-1]
    event["outputs"] = {"Design/specification/spec-review": facts.fingerprint(review)}
    assert facts.proof_valid("m", events, "specification")
    for rel, text in files.items():
        (review / rel).write_text("changed")
        assert not facts.proof_valid("m", events, "specification")
        (review / rel).write_text(text)
    assert facts.proof_valid("m", events, "specification")


def spec_run(module, run):
    """Dispatch+pass specification run N with the intent tree on disk; returns nothing."""
    bm = fp(module, "intent")
    store.append_event(
        module,
        {
            "type": "dispatch",
            "rule": "specification",
            "run": run,
            "workdir": "w",
            "inputs": {"intent": bm},
            "params": {},
        },
        TS,
    )
    store.append_event(
        module,
        {
            "type": "outcome",
            "rule": "specification",
            "run": run,
            "verdict": "pass",
            "outputs": {},
            "proofs": [
                {
                    "name": "specification",
                    "verdict": "pass",
                    "inputs": {"intent": bm},
                }
            ],
            "tool_versions": {},
        },
        TS,
    )


def test_stale_inputs_returns_changed_declared_inputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_file("m", "Design/specification/design.md", "d1")
    write_file("m", "Design/specification/manifest.json", "{}")
    write_file("m", "Design/specification/child_a.md", "a1")
    recorded = {
        "Design/specification/design.md": fp("m", "Design/specification/design.md"),
        "Design/specification/manifest.json": fp(
            "m", "Design/specification/manifest.json"
        ),
        "Design/specification/child_a.md": fp("m", "Design/specification/child_a.md"),
    }
    store.append_event(
        "m",
        {
            "type": "dispatch",
            "rule": "rtl-design",
            "run": 1,
            "workdir": "w",
            "inputs": recorded,
            "params": {},
        },
        TS,
    )
    store.append_event(
        "m",
        {
            "type": "outcome",
            "rule": "rtl-design",
            "run": 1,
            "verdict": "pass",
            "outputs": {},
            "proofs": [
                {
                    "name": "rtl-design",
                    "verdict": "pass",
                    "inputs": recorded,
                }
            ],
            "tool_versions": {},
        },
        TS,
    )
    evs = store.read_events("m")
    assert facts.stale_inputs("m", evs, "rtl-design") == []  # nothing drifted yet
    write_file("m", "Design/specification/child_a.md", "a2-changed")  # one input drifts
    assert facts.stale_inputs("m", evs, "rtl-design") == [
        "Design/specification/child_a.md"
    ]


def test_stale_inputs_empty_without_prior_outcome(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert facts.stale_inputs("m", [], "rtl-design") == []


def test_proof_none_rule_available_despite_invalid_upstream(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # no upstream outcomes at all → normal rules unavailable, but a proof=None rule is available
    evs = store.read_events("m") if (Path("m") / "events.jsonl").exists() else []
    assert facts.rule_available("m", evs, "simulation-triage") is True


# ── The intent tree: one container, one recorded version ───────────────────────
#
# Every rule binds `intent/` as its PIPELINE_INPUT, so one merkle stands for the
# engineer's whole delivery: the document plus whatever they put beside it. These
# tests pin the four properties the container was chosen for — the third one
# (adding the first authority invalidates) is the one a per-entry or
# complement-of-the-pipeline definition cannot give.


def land_every_proof(module):
    """Dispatch+pass all eight proof rules, recording inputs through the real
    kernel resolver so the tree's version is whatever it actually is on disk."""
    import kernel  # local: this module otherwise depends only on facts/rules

    for name, r in rules.RULES.items():
        if not r.proof:
            continue
        inputs = kernel.resolve_inputs(module, name)
        store.append_event(
            module,
            {
                "type": "dispatch",
                "rule": name,
                "run": 1,
                "workdir": f"{name}/runs/1",
                "inputs": inputs,
                "params": {},
            },
            TS,
        )
        store.append_event(
            module,
            {
                "type": "outcome",
                "rule": name,
                "run": 1,
                "verdict": "pass",
                "outputs": {},
                "proofs": [
                    {
                        "name": name,
                        "verdict": "pass",
                        "inputs": inputs,
                    }
                ],
                "tool_versions": {},
            },
            TS,
        )


def proofs():
    return [n for n, r in rules.RULES.items() if r.proof]


def test_intent_tree_is_recorded_as_one_container(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "b1")
    land_every_proof("m")
    evs = store.read_events("m")
    for name in proofs():
        proof = facts.proof_outcome(evs, name)[1]["proofs"][0]
        assert proof["inputs"]["intent"].startswith("merkle:"), name
        assert "intent/brainstorm.md" not in proof["inputs"], name
    assert set(facts.projection("m", evs).values()) == {"valid"}


def test_delivering_the_first_authority_invalidates_every_proof(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "b1")
    land_every_proof("m")
    write_file(
        "m", "intent/refs/registers.md", "the authority"
    )  # engineer adds it later
    evs = store.read_events("m")
    assert set(facts.projection("m", evs).values()) == {"stale"}


def test_editing_an_authority_invalidates_every_proof(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "b1")
    write_file("m", "intent/refs/registers.md", "v1")
    land_every_proof("m")
    evs = store.read_events("m")
    assert set(facts.projection("m", evs).values()) == {"valid"}
    write_file("m", "intent/refs/registers.md", "v2")
    evs = store.read_events("m")
    assert set(facts.projection("m", evs).values()) == {"stale"}
    # A tree change is not a narrowing: it sends decide back to specification, which
    # re-transcribes the document whole, so nothing seeds scope from it.
    assert facts.stale_inputs("m", evs, "specification") == []


def test_writes_outside_the_container_are_not_intent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_file("m", "intent/brainstorm.md", "b1")
    land_every_proof("m")
    # what real runs actually put at a module root: an agent's downloads, a tool's
    # cwd side-effect, a human's report written afterwards
    write_file("m", "jinja2-3.1.6-py3-none-any.whl", "z")
    write_file("m", "parsetab.py", "z")
    write_file("m", "EVALUATION.md", "z")
    evs = store.read_events("m")
    assert set(facts.projection("m", evs).values()) == {"valid"}


def test_container_without_the_entry_document_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (Path("m") / "intent").mkdir(parents=True)
    assert facts.rule_available("m", [], "specification") is False
    write_file("m", "intent/brainstorm.md", "b1")
    assert facts.rule_available("m", [], "specification") is True
    (Path("m") / "intent" / "brainstorm.md").unlink()
    assert facts.rule_available("m", [], "specification") is False


def test_intent_tree_is_unwritable(tmp_path, monkeypatch):
    """The unwritable-input property is enforced by the kernel, not asserted in prose.

    A stage's contract points judges into the intent tree, and a tool that reads a file there
    can write beside it — importing a delivered model.py leaves a __pycache__. Hashing that
    moved the merkle every proof records, so the module went stale on a tree whose delivered
    files were byte-identical. The write is prevented instead, and unconditionally: gating it
    on a run being in flight left the same hole open between rounds, where a reader poking at
    a reaped module invalidated every proof the same way.
    """
    monkeypatch.chdir(tmp_path)
    ref = write_file("m", "intent/reference/model.py", "X = 1\n")
    v = fp("m", "intent")

    store.freeze_inputs("m")

    # The delivered file and every directory above it refuse a write, so no tool can drop a
    # cache beside what it read.
    for p in (ref, ref.parent, Path("m") / "intent"):
        assert not p.stat().st_mode & 0o200, p
    assert fp("m", "intent") == v
    with pytest.raises(PermissionError):
        (ref.parent / "__pycache__").mkdir()

    # Idempotent, and it does not touch group or other: a shared checkout keeps what it had.
    before = ref.stat().st_mode
    store.freeze_inputs("m")
    assert ref.stat().st_mode == before
