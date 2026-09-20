"""Validate the integrated RTL inputs and the separate implementation annotations."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

FILES_NAME = "rtl-files.json"
ANNOTATIONS_NAME = "constraint-annotations.json"
SRC_DIR = "src"

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


def load_ledger(workdir) -> dict:
    """Validate both sidecars and return the ordered compilation inputs."""
    files_path, ann_path = paths(workdir)
    files = _read_validated(files_path, "rtl-files.schema.json")
    _read_validated(ann_path, "constraint-annotations.schema.json")
    return files
