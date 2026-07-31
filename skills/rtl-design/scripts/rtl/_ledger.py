"""rtl._ledger — the two authored sidecars this stage emits, and the merge helper.

`rtl-files.json` (per-child files + incdirs) and `constraint-annotations.json` (per-child
SGDC/SDC annotations) together hold everything the reaped child reports carry. They are split
because their consumers are: simulation declares only the file layout, so bundling the two would
invalidate simulation's proof on an annotation-only edit.

In memory the two are one dict, child -> {files, incdirs?, annotations}, because that is
the shape the child reports arrive in, so a round that re-authors a subset overlays. On disk they
are two files, each validated against its own schema and each separately declarable as a
downstream input.

The stage authors both files itself; load_ledger() reads them back and fails loud rather than
let finalize emit degraded output from partial state.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

FILES_NAME = "rtl-files.json"
ANNOTATIONS_NAME = "constraint-annotations.json"

_REFERENCES = Path(__file__).resolve().parent.parent.parent / "references"


class LedgerError(Exception):
    """Malformed state — finalize must fail loudly, never emit degraded output."""


def _validate(doc: dict, schema_name: str, label: str) -> None:
    try:
        schema = json.loads((_REFERENCES / schema_name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise LedgerError(f"cannot read {schema_name}: {e}") from e
    errors = sorted(
        Draft202012Validator(schema).iter_errors(doc),
        key=lambda x: list(x.absolute_path),
    )
    if errors:
        err = errors[0]
        where = "$" + "".join(
            f"[{q!r}]" if isinstance(q, int) else f".{q}" for q in err.absolute_path
        )
        raise LedgerError(f"{label} schema violation at {where}: {err.message}")


def _read_validated(path: Path, schema_name: str) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise LedgerError(f"cannot read {path}: {e}") from e
    _validate(doc, schema_name, path.name)
    return doc


def paths(workdir) -> tuple[Path, Path]:
    workdir = Path(workdir)
    return workdir / FILES_NAME, workdir / ANNOTATIONS_NAME


def ledger_exists(workdir) -> bool:
    return all(p.is_file() for p in paths(workdir))


def load_ledger(workdir) -> dict:
    """Read + schema-validate both sidecars and merge them into one child -> record dict.

    A child present in one file and absent from the other is a defect, not a partial
    result: the two are written together by the same verb.
    """
    files_path, ann_path = paths(workdir)
    files = _read_validated(files_path, "rtl-files.schema.json")
    anns = _read_validated(ann_path, "constraint-annotations.schema.json")
    if set(files) != set(anns):
        only_f, only_a = sorted(set(files) - set(anns)), sorted(set(anns) - set(files))
        raise LedgerError(
            f"{FILES_NAME} and {ANNOTATIONS_NAME} disagree on the child roster: "
            f"only in files={only_f}, only in annotations={only_a}"
        )
    return {name: {**files[name], "annotations": anns[name]} for name in files}
