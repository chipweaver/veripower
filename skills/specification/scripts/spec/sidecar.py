"""Read the authored JSON sidecars this stage emits — validating on the way in.

Wave 1 authors clocks.json / features.json / top-io.json / interconnects.json, and each
wave-2 child authors check-hints/<child>.json. Every read goes through `read_sidecar`, so a
malformed sidecar is reported by **whichever verb needed it, at the moment it needed it**.
That placement is the point: a file's own shape is not a cross-file property, so it has no
business waiting for a gate that runs after every author has finished. (It used to: the same
file was validated twice by two verbs and a third was validated by neither.)

The error names every violation at once, not the first — whoever is fixing the sidecar wants
the whole list.

Schemas are LOADED from references/, never restated in Python. The one rule JSON Schema cannot
carry — `width` vs the `[h:l]` range a name declares — is registered below against the files it
belongs to, so a file's content rules stay in one place whether or not the schema language can
express them.
"""

import json
import math
import re
from pathlib import Path

from jsonschema import Draft202012Validator

_REFERENCES = Path(__file__).resolve().parent.parent.parent / "references"
_BIT_RANGE_RE = re.compile(r"\[(\d+):(\d+)\]$")


class SidecarError(Exception):
    """A sidecar is missing, unreadable, or violates its own contract."""

    def __init__(self, name: str, violations: list[dict]):
        self.name = name
        self.violations = violations
        detail = "; ".join(
            f"{v.get('at', '')} {v['error']}".strip() for v in violations
        )
        super().__init__(f"{name}: {detail}")


def _width_rule(doc) -> list[dict]:
    """`width` must agree with the `[h:l]` range the name carries — cross-field arithmetic,
    so not expressible in JSON Schema. An `[i]` index (a register-file element) makes no
    width claim and is skipped."""
    out: list[dict] = []
    if not isinstance(doc, list):
        return out
    for e in doc:
        if not isinstance(e, dict):
            continue
        n, w = e.get("name") or e.get("wire"), e.get("width")
        if not isinstance(n, str) or not isinstance(w, int):
            continue
        m = _BIT_RANGE_RE.search(n)
        if m:
            implied = int(m.group(1)) - int(m.group(2)) + 1
            if implied != w:
                out.append(
                    {
                        "at": f"${n}",
                        "error": f"width {w} disagrees with the range in the name "
                        f"(implies {implied})",
                    }
                )
    return out


def _finite_rule(doc) -> list[dict]:
    """A PPA target must be a finite number. `json.loads` accepts the NaN / Infinity tokens
    and `type: number` admits them, and a NaN target makes power-analysis' `actual > target`
    false for every input — silently disarming that gate. Nothing downstream catches it:
    synthesis filters an unrecognized dim away and power-analysis skips a target whose
    scenario_id does not match, so both fail OPEN."""
    out: list[dict] = []
    if not isinstance(doc, list):
        return out
    for i, e in enumerate(doc):
        t = e.get("target") if isinstance(e, dict) else None
        if isinstance(t, float) and not math.isfinite(t):
            out.append({"at": f"$[{i}].target", "error": f"must be finite (got {t!r})"})
    return out


_CONTENT_RULES = {
    "top-io.json": _width_rule,
    "interconnects.json": _width_rule,
    "ppa.json": _finite_rule,
}


def validate_doc(name: str, doc, schema: str | None = None) -> list[dict]:
    """Every violation in an already-parsed sidecar doc — schema first, then the content
    rules JSON Schema cannot carry. Separate from `read_sidecar` for the one caller that
    validates a doc it has in hand before writing it (finalize's --ppa-targets override): a
    malformed override must not reach disk.

    An unreadable schema is itself a violation, so a caller can never wave a doc through
    because the schema went missing."""
    schema_path = _REFERENCES / (schema or f"{Path(name).stem}.schema.json")
    try:
        schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [{"error": f"{schema_path.name} unreadable: {exc}"}]
    violations = [
        {
            "at": "$"
            + "".join(
                f"[{q!r}]" if isinstance(q, int) else f".{q}" for q in err.absolute_path
            ),
            "error": err.message,
        }
        for err in sorted(
            Draft202012Validator(schema_doc).iter_errors(doc),
            key=lambda e: list(e.absolute_path),
        )
    ]
    return violations + _CONTENT_RULES.get(name, lambda _doc: [])(doc)


def read_sidecar(workdir, name: str, schema: str | None = None) -> list[dict]:
    """One sidecar's entries, validated. Raises SidecarError naming every violation.
    `schema` overrides the filename-derived schema, for sidecars named after their subject
    (check-hints/<child>)."""
    try:
        doc = json.loads((Path(workdir) / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SidecarError(name, [{"error": "missing"}]) from None
    except (OSError, json.JSONDecodeError) as exc:
        raise SidecarError(name, [{"error": f"unreadable: {exc}"}]) from None
    violations = validate_doc(name, doc, schema)
    if violations:
        raise SidecarError(name, violations)
    return doc
