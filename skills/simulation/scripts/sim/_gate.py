#!/usr/bin/env python3
"""The three gate primitives finalize re-runs before it will write a pass.

  materialization_errors  every sequences[]/agents[] SV file present; no TODO residue.
  check_review_flagged     the testpoints the reviewer marked BLOCKING in its own record.
  coverage_gate           structural-coverage.json carries the DUT's own per-module row, and each coverage
                          bound requirements.json assigns to simulation holds (a null or '--'
                          dim is skipped; a bounded dim urg did not measure fails).

check-materialization calls the first as the env child's own early exit, which saves a
regression run on a hollow TB. The other two have no caller but finalize: reading them is
what makes the pass conditional on something other than the main thread's account of them.
Status truth is the caller's exit code, not narration.
"""

from __future__ import annotations

import json
import operator
import re
from pathlib import Path

_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}

# A finding heading in check-review.md. The testpoint is the first token after the
# hashes and the marker is the last, so a locus carrying spaces still parses.
_FINDING = re.compile(r"^##\s+(?P<tp_id>\S+)\s+(?P<rest>.*?)\s*$")

# Policy: ANY "TODO" in a materialized TB == unfinished work -> fail (a completed TB carries zero
# "TODO" anywhere) — the deliberate deliverable rule the env child's contract states as "any TODO
# marker survives in tb/uvm/**". The broad match rests on canonical templates carrying no
# non-marker "TODO" prose (base_seq.sv uses NOTE), which is not left to this comment:
# tests/contracts/test_templates_todo_free.py asserts it over every shipped template, so a
# template edit that broke it fails there rather than failing every run of this gate.
_TODO_RE = re.compile(r"TODO")


def coverage_rows(requirements_path: Path) -> list[dict]:
    """The requirements.json rows simulation judges with a coverage bound: the engineer's own
    thresholds, in the engineer's own comparison. No row for a dim means that dim is reported,
    not gated."""
    rows = json.loads(Path(requirements_path).read_text(encoding="utf-8"))
    return [
        r
        for r in rows
        if r["judge"] == "simulation"
        and r.get("target", {}).get("dim", "").startswith("coverage_")
    ]


def materialization_errors(workdir: Path, scaffold: dict) -> list[str]:
    """Required SV files present, and no TODO residue. The renderer guarantees most of the
    files, so what this catches is a stub the agent left unfilled or a file it deleted or
    overwrote. Canonical templates carry no non-marker TODO prose, so a match is always a real
    unfilled marker."""
    module = scaffold.get("module", "")
    errs: list[str] = []
    for seq in scaffold.get("sequences", []):
        f = workdir / "tb/uvm/seq" / f"{module}_{seq.get('name')}_seq.sv"
        if not f.is_file():
            errs.append(
                f"missing sequence file {f.relative_to(workdir)} "
                f"(bootstrap renders it; was it deleted?)"
            )
    for ag in scaffold.get("agents", []):
        name = ag.get("name")
        need = [f"{module}_{name}_monitor.sv", f"{module}_{name}_agent.sv"]
        if ag.get("mode") == "active":
            need.append(f"{module}_{name}_driver.sv")
        for fn in need:
            f = workdir / "tb/uvm/agent" / fn
            if not f.is_file():
                errs.append(f"missing agent file {f.relative_to(workdir)}")
    # An agent the plan gained gets its classes rendered and its interface instantiated in
    # tb_top, and stops there: the env is carried, so it neither builds nor connects the new
    # agent. That compiles clean and drives nothing, which is why it is caught here — measured
    # on tpu_top, and every shipped TB across two designs already satisfies it.
    env = workdir / "tb/uvm/env" / f"{module}_env.sv"
    if not env.is_file():
        errs.append(f"missing env file {env.relative_to(workdir)}")
    else:
        env_text = env.read_text(encoding="utf-8", errors="ignore")
        for ag in scaffold.get("agents", []):
            name = ag.get("name")
            if name and name not in env_text:
                errs.append(
                    f"{env.name} never names {name} (the plan declares it; the renderer wrote "
                    f"its classes and tb_top's interface, and an env that does not build it "
                    f"compiles clean and drives nothing)"
                )
    tb = workdir / "tb" / "uvm"
    if tb.is_dir():
        for sv in sorted(set(tb.rglob("*.sv")) | set(tb.rglob("*.svh"))):
            if _TODO_RE.search(sv.read_text(encoding="utf-8", errors="ignore")):
                errs.append(
                    f"TODO residue in {sv.relative_to(workdir)} "
                    f"(fill the scaffold; no TODO may survive in a completed TB)"
                )
    return errs


def coverage_gate(
    cov: dict | None, rows: list[dict], dut: str
) -> tuple[list[str], list[dict]]:
    """Extractable, scoped to the DUT, and every bounded dim satisfies its row (a null dim is
    skipped). Returns (errors, one {id, met, actual, measured} entry per row) — `measured` names the
    row of the report the number came from, so a verdict cannot be read without seeing what
    scope produced it.

    Scored against the DUT's own row in `per_module`, never the report's `aggregate`. The
    aggregate is the TB top's whole instance tree — the DUT plus every agent interface plus
    every ROM the design instantiates — so it is a mixture the engineer's row never asked
    about, and the mixture reads high wherever those companions are fully swept. On a real run
    it read toggle 92.57 where the DUT itself was 76.37, and passed a `> 90` bound the DUT
    misses by 13 points. A DUT row the report does not carry is a failure to attribute
    coverage, never a reason to score something else instead."""
    per = (cov or {}).get("per_module")
    if not isinstance(per, list) or not per:
        return (
            [
                "coverage not extractable: structural-coverage.json missing or carries no "
                "per-module rows (urg did not produce a parseable report; cannot gate -> "
                "fail, never claim met)"
            ],
            [],
        )
    agg = next((m for m in per if m.get("name") == dut), None)
    if agg is None:
        return (
            [
                f"coverage not attributable: no per-module row named {dut!r} in "
                f"structural-coverage.json (rows: {sorted(m.get('name') for m in per)}) — "
                "the DUT's own coverage is what the row bounds"
            ],
            [],
        )
    errs: list[str] = []
    judged: list[dict] = []
    for r in rows:
        t = r["target"]
        dim = t["dim"].removeprefix("coverage_")
        if (
            dim not in agg
        ):  # urg never measured this dim -> cannot gate it -> fail (not silent skip)
            judged.append(
                {
                    "id": r["id"],
                    "met": False,
                    "actual": None,
                    "measured": f"{dim} coverage of {dut!r}: urg measured none",
                }
            )
            errs.append(
                f"{r['id']}: {dim} coverage is bounded but absent from the coverage report "
                f"(urg did not measure it; cannot gate)"
            )
            continue
        val = agg[dim]
        if (
            val is None
        ):  # measured as N/A ('--', e.g. a DUT with no FSM) -> skip, do not fail
            judged.append(
                {
                    "id": r["id"],
                    "met": True,
                    "actual": None,
                    "measured": f"{dim} coverage of {dut!r}: reported N/A by urg",
                }
            )
            continue
        ok = _OPS[t["op"]](val, t["value"])
        judged.append(
            {
                "id": r["id"],
                "met": ok,
                "actual": val,
                "measured": f"{dim} coverage of the DUT {dut!r}, from the per-module row of "
                f"structural-coverage.json (not the TB top aggregate)",
            }
        )
        if not ok:
            errs.append(
                f"{r['id']}: {dim} coverage {val} is not {t['op']} {t['value']}"
            )
    return errs, judged


def check_review_flagged(review_path: Path) -> list[str]:
    """The testpoints the reviewer marked BLOCKING, read off its own record.

    Whether a finding stops the round is the reviewer's call, made in one place and in one
    word. Nothing here re-derives it from anything else, and nothing reads the prose."""
    text = Path(review_path).read_text(encoding="utf-8")
    flagged = [
        m.group("tp_id")
        for m in (_FINDING.match(ln) for ln in text.splitlines())
        if m and m.group("rest").split()[-1:] == ["BLOCKING"]
    ]
    return sorted(set(flagged))
