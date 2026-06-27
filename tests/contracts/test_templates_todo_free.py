# tests/unit/test_templates_todo_free.py
"""A completed TB must carry zero "TODO" anywhere, so the canonical templates may contain "TODO"
ONLY in real fill markers (`// TODO(...)` or the no-seq test's `// TODO: Start sequences here.`),
never in infra base classes or provenance headers."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "skills/simulation/templates/infra"
SCAFFOLD = ROOT / "skills/simulation/templates/scaffold"

# A "TODO" is allowed only as a fill marker: TODO( ... ) or the literal start-seq marker.
# (The start-seq branch is inert for *templates* — that marker is emitted by the render-scaffold verb
# into generated files; the branch is kept so this regex matches the sim check-materialization scanner.)
_MARKER = re.compile(r"TODO\(|TODO: Start sequences here\.")


def _bad_todo_lines(path: Path):
    return [
        ln
        for ln in path.read_text().splitlines()
        if "TODO" in ln and not _MARKER.search(ln)
    ]


def test_infra_sv_has_no_todo():
    # base_seq.sv reworded; base_test.sv already clean; no infra .sv may carry any TODO.
    for sv in INFRA.rglob("*.sv"):
        assert "TODO" not in sv.read_text(), f"{sv} still contains TODO"


def test_scaffold_headers_have_no_nonmarker_todo():
    # provenance headers reworded off "TODO"; only real fill markers may remain.
    for sv in SCAFFOLD.glob("*.sv"):
        assert _bad_todo_lines(sv) == [], (
            f"{sv} has non-marker TODO: {_bad_todo_lines(sv)}"
        )


def test_real_fill_markers_survive():
    # the cleanup must NOT delete any of the agent's fill markers.
    blob = "".join(p.read_text() for p in SCAFFOLD.glob("*.sv"))
    for marker in (
        "TODO(sequence)",
        "TODO(rm)",
        "TODO(scoreboard)",
        "TODO(driver)",
        "TODO(monitor)",
        "TODO(transaction)",
        "TODO(interface)",
    ):
        assert f"// {marker}" in blob, f"fill marker {marker} was deleted"
