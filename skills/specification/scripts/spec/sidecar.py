"""Read the authored JSON sidecars this stage emits — validating on the way in.

The transcriber authors requirements.json; the decomposer authors clocks.json / top-io.json /
interconnects.json; each child authors check-hints/<child>.json. Every read goes through `read_sidecar`, so a
malformed sidecar is reported by **whichever verb needed it, at the moment it needed it**.
That placement is the point: a file's own shape is not a cross-file property, so it has no
business waiting for a gate that runs after every author has finished.

The error names every violation at once, not the first — whoever is fixing the sidecar wants
the whole list.

Schemas are LOADED from references/, never restated in Python. The rules JSON Schema cannot
carry — cross-field arithmetic, uniqueness, the finiteness of a number `json.loads` already
accepted — are registered below against the files they belong to, so a file's content rules
stay in one place whether or not the schema language can express them.
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


def _base_name_rule(doc) -> list[dict]:
    """A top-IO `name` is the base identifier alone; `width` carries the width.

    The string reaches `get_ports` and `abstract_port` verbatim, and the TB signal and
    transaction-field declarations verbatim. A bit range survives none of that trip: DC and
    PrimeTime match zero ports for `get_ports token_in[4:0]`, so the port loses its IO
    constraint and the STA grades a design it never fully timed; the UVM field macro built
    from the same string will not compile. A parameterized declaration is worse still —
    `[DATA_WIDTH-1:0]` names a parameter no tool downstream evaluates.

    Detecting the two forms disagreeing (_width_rule) cannot reach any of that, because the
    range is wrong here even when it agrees with `width`.
    """
    out: list[dict] = []
    if not isinstance(doc, list):
        return out
    for e in doc:
        if not isinstance(e, dict):
            continue
        n = e.get("name")
        if isinstance(n, str) and "[" in n:
            out.append(
                {
                    "at": f"${n}",
                    "error": "name carries a bit range; write the base identifier and "
                    "let width carry it",
                }
            )
    return out


# The dims a judging stage's script compares; every other judge takes no target.
def _requirements_rule(doc) -> list[dict]:
    """What the ledger's schema cannot say: ids are unique; a scenario only qualifies
    power_mw; a value is finite (which dim a judge can compare is the judge's own fact, refused
    by the stage that would have to measure it) (`json.loads` accepts NaN / Infinity and `type: number` admits them, and a NaN
    bound makes every comparison false — a gate silently disarmed)."""
    out: list[dict] = []
    if not isinstance(doc, list):
        return out
    seen: dict[str, int] = {}
    for i, r in enumerate(doc):
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        if rid in seen:
            out.append(
                {"at": f"$[{i}].id", "error": f"{rid!r} already used at $[{seen[rid]}]"}
            )
        seen.setdefault(rid, i)
        t = r.get("target")
        if not isinstance(t, dict):
            continue
        if "scenario" in t and t.get("dim") != "power_mw":
            out.append(
                {
                    "at": f"$[{i}].target.scenario",
                    "error": "only a power_mw bound names a scenario",
                }
            )
        v = t.get("value")
        if isinstance(v, float) and not math.isfinite(v):
            out.append(
                {"at": f"$[{i}].target.value", "error": f"must be finite (got {v!r})"}
            )
    return out


_CONTENT_RULES = {
    # top-io names reach three tools verbatim, so the range is banned outright rather
    # than cross-checked. interconnects wires reach none of them — they are read by the
    # rtl-design children as prose — so there the cross-check still applies.
    "top-io.json": _base_name_rule,
    "interconnects.json": _width_rule,
    "requirements.json": _requirements_rule,
}


def validate_doc(name: str, doc, schema: str | None = None) -> list[dict]:
    """Every violation in an already-parsed sidecar doc — schema first, then the content
    rules JSON Schema cannot carry.

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
