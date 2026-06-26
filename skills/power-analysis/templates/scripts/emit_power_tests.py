#!/usr/bin/env python3
"""Render UVM power test classes from scaffold-specification.json.

Direction C: power-analysis does NOT define its own UVM sequence classes.
Instead each rendered test class invokes the simulation-compiled
``{module}_{sequence_ref}_seq`` (already in ``{module}_tb_pkg``) through
the corresponding agent's ``m_sequencer``.

Reads ``power_scenarios[]``, dedups by ``sequence_ref``, renders one
``power_<seq>_test.sv`` per unique ``sequence_ref``. Writes
``power_filelist.f`` listing the generated test files only.

Cross-stage contract enforced here:
- ``power_scenarios[].sequence_ref`` MUST exist as ``sequences[].name``
  in the same plan (else simulation TB has not compiled the seq class).
- ``sequences[].agent`` MUST be non-empty (used to construct the env
  member field ``m_<agent>_agent`` for the sequencer handle).

Either condition violated → script fails closed (exit 1).

Called by the power bootstrap verb on first deploy and by
``make refresh-tests`` on every gls-compile.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True, type=Path)
    p.add_argument(
        "--module",
        required=True,
        help="Module name; matches simulation tb_pkg / class prefix.",
    )
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--filelist", required=True, type=Path)
    p.add_argument("--top", required=True)
    p.add_argument("--test-tmpl", required=True, type=Path)
    return p.parse_args()


def render(template: str, mapping: dict[str, str]) -> str:
    out = template
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def write_if_changed(path: Path, content: str) -> bool:
    """Write content to path only if it differs from existing content.

    Returns True if file was written/created; False if unchanged.
    Preserves mtime when content matches → VCS won't re-compile unchanged TB.
    """
    if path.is_file() and path.read_text() == content:
        return False
    path.write_text(content)
    return True


def main() -> int:
    args = parse_args()

    for label, path in [("plan", args.plan), ("test-tmpl", args.test_tmpl)]:
        if not path.is_file():
            print(
                f"[emit_power_tests] ERROR: --{label} not found: {path}",
                file=sys.stderr,
            )
            return 1

    plan = json.loads(args.plan.read_text())
    sequences = plan.get("sequences", [])
    scenarios = plan.get("power_scenarios", [])

    # Build sequence_ref → agent map (sequences[].name → sequences[].agent).
    # power_scenarios[].sequence_ref MUST appear in this map (cross-stage contract).
    seq_to_agent: dict[str, str] = {}
    for s in sequences:
        name = s.get("name")
        agent = s.get("agent")
        if not name:
            continue
        if not agent:
            print(
                f"[emit_power_tests] ERROR: sequences[].name={name!r} has no agent field "
                f"— cannot resolve env member m_<agent>_agent.",
                file=sys.stderr,
            )
            return 1
        seq_to_agent[name] = agent

    args.out_dir.mkdir(parents=True, exist_ok=True)
    test_tmpl = args.test_tmpl.read_text()

    seen: set[str] = set()
    filelist_lines: list[str] = []
    for s in scenarios:
        seq = s.get("sequence_ref", "")
        if not seq or seq in seen:
            continue
        seen.add(seq)
        if seq not in seq_to_agent:
            print(
                f"[emit_power_tests] ERROR: power_scenarios[].sequence_ref={seq!r} "
                f"not found in sequences[].name — simulation TB has not compiled this "
                f"seq class. Fix in Verification/simulation-plan/scaffold-specification.json: "
                f"either add a matching entry to sequences[] (with name={seq!r} + an "
                f"agent), or change power_scenarios[].sequence_ref to an existing "
                f"sequences[].name. Field semantics: "
                f"skills/simulation-plan/references/power-scenarios-template.md.",
                file=sys.stderr,
            )
            return 1
        agent_name = seq_to_agent[seq]
        mapping = {
            "MODULE": args.module,
            "TOP": args.top,
            "SEQUENCE_REF": seq,
            "AGENT_NAME": agent_name,
            "SCENARIO_ID": s.get("id", ""),
            "SCENARIO_DESC": s.get("scenario", ""),
            "DURATION_CYCLES": str(s.get("duration_cycles", 1000)),
        }
        test_out = args.out_dir / f"power_{seq}_test.sv"
        write_if_changed(test_out, render(test_tmpl, mapping))
        filelist_lines.append(str(test_out))

    filelist_content = "\n".join(filelist_lines) + ("\n" if filelist_lines else "")
    changed = write_if_changed(args.filelist, filelist_content)
    print(
        f"[emit_power_tests] generated {len(filelist_lines)} test classes "
        f"({len(seen)} unique sequence_ref values) → {args.filelist}"
        f"{' (unchanged)' if not changed else ''}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
