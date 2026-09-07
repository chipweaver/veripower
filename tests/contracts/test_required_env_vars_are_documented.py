"""Every environment variable an env.sh refuses to run without is named where people look.

`env.sh` is what stops the run: `VAR="${VAR:?ERROR ...}"` aborts the shell before any tool
starts. The README beside it is what the engineer reads to find out what to export, and the two
drifted — synthesis gained a second required variable and its README went on naming one, so
following the README got you an abort on a variable it had never mentioned.

Two readers, so two assertions. The README beside `env.sh` serves the engineer already in a run
directory; `docs/eda-env.md` serves whoever is provisioning the machine, before any check can
run — and that one is the harder link to keep, because adding a guard and adding a deployment row
happen in different files at different times.

Mechanical, because the fact is: whatever env.sh makes mandatory, both say out loud. An env.sh
that makes nothing mandatory (lint-cdc's) has nothing to say and is not a case here; the
module-level assertion below is what catches the pattern itself going stale.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# `VAR="${VAR:?...}"` — the form that aborts. `${VAR:-default}` is optional and not checked.
MANDATORY = re.compile(r"\$\{([A-Z][A-Z0-9_]*):\?")


def _cases():
    out = []
    for p in sorted(ROOT.glob("skills/*/templates/**/env.sh")):
        if not (p.parent / "README.md").is_file():
            continue
        required = sorted(set(MANDATORY.findall(p.read_text())))
        if required:
            out.append((p, required))
    return out


CASES = _cases()
assert CASES, "no env.sh makes anything mandatory; the `${VAR:?...}` pattern moved"


@pytest.mark.parametrize(
    "env_sh,required",
    CASES,
    ids=[str(p.relative_to(ROOT / "skills")).split("/")[0] for p, _ in CASES],
)
def test_readme_names_every_mandatory_env_var(env_sh, required):
    readme = (env_sh.parent / "README.md").read_text()
    missing = [v for v in required if v not in readme]
    assert not missing, (
        f"{env_sh.parent / 'README.md'} does not name {missing}, which "
        f"{env_sh.name} refuses to run without"
    )


def test_eda_env_names_every_mandatory_env_var():
    doc = (ROOT / "docs/eda-env.md").read_text()
    required = sorted({v for _, vs in CASES for v in vs})
    missing = [v for v in required if v not in doc]
    assert not missing, (
        f"docs/eda-env.md does not name {missing}, which a stage env.sh refuses to run without"
    )
