"""Every command line a skill documents must be one its CLI actually accepts.

CONTRIBUTING calls this sync mandatory — a SKILL.md is the complete runtime contract for the
scripts it invokes, because agents run them per the documented lines rather than reading their
source. Nothing enforced it. The drift it is meant to prevent has happened: three of the five
finalize lines `simulation` documented passed a `--failure-phase` flag, which cost six blocked
outcomes across the shipped runs before it was found by hand.

So the check is mechanical: pull every `bash` block out of the agent-facing prose, resolve the
CLI it names, and ask that CLI whether the verb and every long flag exist. Re-introducing the
`--failure-phase` line makes this fail, as does renaming a verb.

One block is deliberately unreachable: design-flow's kernel dispatch passes `dispatch_args`
verbatim from `decide`, so the prose has a placeholder where a verb would be.
"""

import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BLOCK = re.compile(r"```bash\n(.*?)```", re.S)
LONG_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
VERB = re.compile(r"[a-z][a-z-]*\Z")


def _cli_for(cmd: str, skill: str) -> Path | None:
    if "kernel.py" in cmd:
        return ROOT / "framework/scripts/kernel.py"
    m = re.search(r"<skill>/scripts/([a-z_]+)(?:/__main__\.py)?", cmd)
    if not m:
        return None
    base = ROOT / "skills" / skill / "scripts" / m.group(1)
    return base / "__main__.py" if (base / "__main__.py").is_file() else base


def _documented():
    for md in sorted(
        (ROOT / "skills").glob("*/SKILL.md"),
    ) + sorted((ROOT / "skills").glob("*/references/*.md")):
        skill = md.relative_to(ROOT / "skills").parts[0]
        for block in BLOCK.findall(md.read_text(encoding="utf-8")):
            cmd = " ".join(block.replace("\\\n", " ").split())
            cli = _cli_for(cmd, skill)
            if cli is None or not cli.exists():
                continue
            tail = cmd.split(cli.name)[-1] if cli.name in cmd else cmd
            words = [
                w
                for w in tail.split()
                if not w.startswith(("-", "<", "{", "[", "'", '"'))
            ]
            if not words or not VERB.match(words[0]):
                continue
            yield (
                str(md.relative_to(ROOT)),
                cli,
                words[0],
                tuple(sorted(set(LONG_FLAG.findall(tail)))),
            )


CASES = list(_documented())


@lru_cache(maxsize=None)
def _help(cli: Path, verb: str):
    r = subprocess.run(
        [sys.executable, str(cli), verb, "--help"], capture_output=True, text=True
    )
    return r.returncode, r.stdout


def test_every_skill_command_block_is_checked():
    # A guard nothing reaches is not a guard. If this drops, a documented command stopped
    # being resolvable and is now silently unchecked. Lowering the floor is only correct when a
    # command was deliberately deleted — last: specification's derive-ports, with the roster
    # it computed.
    assert len(CASES) >= 24


@pytest.mark.parametrize(
    "md,cli,verb,flags", CASES, ids=[f"{c[0]}:{c[2]}" for c in CASES]
)
def test_documented_command_is_accepted(md, cli, verb, flags):
    rc, out = _help(cli, verb)
    assert rc == 0, f"{md} documents `{verb}`, which {cli.name} does not accept"
    for flag in flags:
        assert flag in out, (
            f"{md} documents `{verb} {flag}`, which {cli.name} does not accept"
        )
