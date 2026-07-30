"""Read + schema-validate the authored JSON sidecars this stage emits.

Wave 1 authors clocks.json / features.json / top-io.json /
interconnects.json, and each wave-2 child authors check-hints/<child>.json. Three verbs
consume them (derive-constraints, derive-ports, check-coverage), which is why the two
readers live here rather than in whichever verb needed them first.

Schemas are LOADED from references/, never restated in Python.
"""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

_REFERENCES = Path(__file__).resolve().parent.parent.parent / "references"


def load_sidecar(workdir: Path, name: str) -> list[dict]:
    """A sidecar's entries. A missing/malformed file yields [] — validate_sidecar reports
    it, so no caller sees a half-parsed list."""
    try:
        doc = json.loads((Path(workdir) / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return doc if isinstance(doc, list) else []


def validate_sidecar(workdir: Path, name: str, schema: str | None = None) -> list[dict]:
    """One sidecar against its schema, returned as violations rather than raised: a gate
    names every defect instead of stopping at the first. `schema` overrides the
    filename-derived schema, for sidecars named after their subject (check-hints/<child>)."""
    schema_path = _REFERENCES / (schema or f"{Path(name).stem}.schema.json")
    try:
        doc = json.loads((Path(workdir) / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [{"error": f"{name} missing"}]
    except (OSError, json.JSONDecodeError) as exc:
        return [{"error": f"{name} unreadable: {exc}"}]
    try:
        schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [{"error": f"{schema_path.name} unreadable: {exc}"}]
    out: list[dict] = []
    for err in sorted(
        Draft202012Validator(schema_doc).iter_errors(doc),
        key=lambda e: list(e.absolute_path),
    ):
        where = "$" + "".join(
            f"[{q!r}]" if isinstance(q, int) else f".{q}" for q in err.absolute_path
        )
        out.append({"at": where, "error": err.message})
    return out
