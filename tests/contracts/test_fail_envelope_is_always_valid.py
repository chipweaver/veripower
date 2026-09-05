"""No stage may write a status=fail envelope its own schema rejects.

Measured in production before this existed: 129 outcomes across 5 real runs on 2 designs,
10 blocked, and **6 of them were `simulation` blocked on `schema_violation`** — the stage's
own documented route-out commands omitted `--fail-reason`, `finalize` wrote
`fail_reason: ""`, and the envelope schema rejects an empty one. A blocked outcome promotes
nothing, so each of those cost the round.

The invariant is the one that was missing, not the flag that happened to carry it: a stage
that cannot name a reason must refuse to write, loudly, rather than emit a record the reap
will throw away.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from framework.scripts import facts

ROOT = Path(__file__).resolve().parents[2]

# stage -> (CLI, the argv that declares a failure with no reason behind it)
_DECLARE_FAILURE = {
    "synthesis": (
        "skills/synthesis/scripts/synthesis/__main__.py",
        ["--fail-reason", ""],
    ),
    "timing-analysis": (
        "skills/timing-analysis/scripts/timing/__main__.py",
        ["--fail-reason", ""],
    ),
    "power-analysis": (
        "skills/power-analysis/scripts/power/__main__.py",
        ["--fail-reason", ""],
    ),
    "lint-cdc": ("skills/lint-cdc/scripts/lintcdc/__main__.py", ["--fail-reason", ""]),
    "simulation": (
        "skills/simulation/scripts/sim/__main__.py",
        ["--phase", "fail", "--fail-reason", ""],
    ),
}


@pytest.mark.parametrize("stage", sorted(_DECLARE_FAILURE))
def test_empty_reason_never_reaches_disk_as_a_fail_envelope(stage, tmp_path):
    cli, argv = _DECLARE_FAILURE[stage]
    wd = tmp_path / stage
    wd.mkdir()
    proc = subprocess.run(
        [sys.executable, str(ROOT / cli), "finalize", "--workdir", str(wd), *argv],
        capture_output=True,
        text=True,
        cwd=wd,
    )
    rj = wd / "result.json"
    if not rj.is_file():
        assert proc.returncode != 0, (
            f"{stage}: wrote nothing but exited 0 — a caller cannot tell that from success"
        )
        return
    env = json.loads(rj.read_text())
    if env.get("status") != "fail":
        return  # took the gate path instead; not this test's subject
    err = facts.validate_result(stage, env)
    assert err is None, (
        f"{stage}: finalize wrote a status=fail envelope its own schema rejects ({err}). "
        f"At reap that is a blocked outcome, not a routable fail, and the round is lost."
    )
