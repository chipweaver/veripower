"""spec seed — whitelist no-clobber carry of prior canonical PRODUCTS (incl. coverage.json
and ppa.json — a fail-finalized rework promotes a present-only artifact set, and an
absent ppa.json would be GC'd out of canonical, severing synthesis/power's declared
input). result.json and the judged spec-review.json are never seeded (room-birth
hygiene, §7.2)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills/specification/scripts"))
from spec import seed  # noqa: E402


def _canonical(tmp_path):
    c = tmp_path / "canonical"
    (c / "constraints").mkdir(parents=True)
    (c / "design.md").write_text("D", encoding="utf-8")
    (c / "manifest.json").write_text("{}", encoding="utf-8")
    (c / "child_a.md").write_text("CA", encoding="utf-8")
    (c / "spec-review.json").write_text('{"pin":1}', encoding="utf-8")
    (c / "constraints" / "m.sdc").write_text("S", encoding="utf-8")
    (c / "constraints" / "m.sgdc").write_text("G", encoding="utf-8")
    (c / "coverage.json").write_text('{"verdict":"pass"}', encoding="utf-8")
    (c / "ppa.json").write_text("[]", encoding="utf-8")
    # the adjudication envelope that must NEVER be carried into a fresh room
    (c / "result.json").write_text('{"status":"pass"}', encoding="utf-8")
    (c / "runs").mkdir()
    (c / "runs" / "1").mkdir()
    (c / "runs" / "1" / "stale.txt").write_text("X", encoding="utf-8")
    (c / ".promote-tmp").mkdir()
    (c / ".promote-tmp" / "leftover.md").write_text("L", encoding="utf-8")
    return c


def test_seed_carries_products_never_adjudication(tmp_path):
    c = _canonical(tmp_path)
    wd = tmp_path / "canonical" / "runs" / "2"
    wd.mkdir(parents=True)
    seed.run(wd, canonical=c)
    for rel in [
        "design.md",
        "manifest.json",
        "child_a.md",
        "coverage.json",
        "ppa.json",  # carried: a fail-finalized rework must not GC it out of canonical
        "constraints/m.sdc",
        "constraints/m.sgdc",
    ]:
        assert (wd / rel).read_text() == (c / rel).read_text(), rel
    # adjudication artifacts stay out — a workdir result.json exists iff this run wrote it
    assert not (wd / "result.json").exists()
    assert not (wd / "spec-review.json").exists()  # judged review is never carried
    assert not (wd / "runs").exists()  # prior run workdirs are never carried
    assert not (wd / ".promote-tmp").exists()  # promote internals never carried


def test_seed_no_clobber_keeps_fresh_work(tmp_path):
    c = _canonical(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "design.md").write_text("FRESH", encoding="utf-8")
    seed.run(wd, canonical=c)
    assert (wd / "design.md").read_text() == "FRESH"  # never overwritten
    assert (wd / "manifest.json").read_text() == "{}"  # still carried
