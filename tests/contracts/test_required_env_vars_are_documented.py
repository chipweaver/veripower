"""Required execution settings must be discoverable in the environment guide."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# `VAR="${VAR:?...}"` — the form that aborts. `${VAR:-default}` is optional and not checked.
MANDATORY = re.compile(r"\$\{([A-Z][A-Z0-9_]*):\?")


def _cases():
    out = []
    for p in sorted(ROOT.glob("skills/*/templates/**/env.sh")):
        required = sorted(set(MANDATORY.findall(p.read_text())))
        if required:
            out.append((p, required))
    return out


CASES = _cases()
assert CASES, "no env.sh makes anything mandatory; the `${VAR:?...}` pattern moved"


def test_eda_env_names_every_mandatory_env_var():
    doc = (ROOT / "docs/eda-env.md").read_text()
    required = sorted({v for _, vs in CASES for v in vs})
    missing = [v for v in required if v not in doc]
    assert not missing, (
        f"docs/eda-env.md does not name {missing}, which a stage env.sh refuses to run without"
    )
