"""simplan._plan — the plan's three sidecars: their names, their schemas, and the merge.

`tb-scaffold.json` (what simulation builds the TB from), `sequences.json` (the roster both
consumers read) and `power-scenarios.json` (power-analysis's alone) together hold everything the
plan carries in machine form. They are three files so each consumer declares only what it reads
(rules.py).

The name-to-schema table lives here rather than in either verb: materialize-scaffold runs before
check-scaffold, so it must not import from the gate, and result.py enumerates the same set a
third time. load_plan then merges them, because one dict is the shape the referential-integrity
checks operate on — `power_scenarios[].sequence_ref` and `tests[].seqs[]` both resolve against
`sequences[]`. Each file is still validated against its own schema on the way in.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCAFFOLD_NAME = "tb-scaffold.json"
SEQUENCES_NAME = "sequences.json"
SCENARIOS_NAME = "power-scenarios.json"

# (filename, schema, the merged-dict key it lands under; None = merged at the top level)
_FILES = (
    (SCAFFOLD_NAME, "tb-scaffold.schema.json", None),
    (SEQUENCES_NAME, "sequences.schema.json", "sequences"),
    (SCENARIOS_NAME, "power-scenarios.schema.json", "power_scenarios"),
)

SIDECAR_NAMES = tuple(name for name, _, _ in _FILES)

_REFERENCES = Path(__file__).resolve().parent.parent.parent / "references"


class PlanError(Exception):
    """Malformed or absent plan state — the gate must fail loudly."""


def paths(workdir) -> tuple[Path, ...]:
    workdir = Path(workdir)
    return tuple(workdir / name for name, _, _ in _FILES)


def _read_validated(path: Path, schema_name: str):
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise PlanError(f"{path.name} missing: {path}") from e
    except json.JSONDecodeError as e:
        raise PlanError(f"{path} is not valid JSON: {e}") from e
    except OSError as e:
        raise PlanError(f"cannot read {path}: {e}") from e
    try:
        schema = json.loads((_REFERENCES / schema_name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise PlanError(f"cannot read {schema_name}: {e}") from e
    errors = sorted(
        Draft202012Validator(schema).iter_errors(doc),
        key=lambda x: list(x.absolute_path),
    )
    if errors:
        err = errors[0]
        where = "$" + "".join(
            f"[{q!r}]" if isinstance(q, int) else f".{q}" for q in err.absolute_path
        )
        raise PlanError(
            f"{path.name} schema violation at {where}: {err.message} "
            f"(validator={err.validator})"
        )
    return doc


def load_plan(workdir) -> dict:
    """Read + schema-validate all three sidecars and merge them into one dict.

    `tb-scaffold.json` keeps `additionalProperties: true` so it tolerates the fields
    materialize injects, which means a `sequences` or `power_scenarios` key left behind in it
    would validate and then be silently replaced by the merge. That is the one way this split
    can regress into two homes, so it is rejected by name.
    """
    merged: dict = {}
    for name, schema_name, key in _FILES:
        doc = _read_validated(Path(workdir) / name, schema_name)
        if key is None:
            stray = [k for k in ("sequences", "power_scenarios") if k in doc]
            if stray:
                raise PlanError(
                    f"{name} carries {stray} — those live in {SEQUENCES_NAME} / "
                    f"{SCENARIOS_NAME}. Remove them from {name}."
                )
            merged.update(doc)
        else:
            merged[key] = doc
    return merged
