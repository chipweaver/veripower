"""spec seed — no-clobber carry-forward of prior canonical outputs incl. the review record."""

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
    (c / "runs").mkdir()
    (c / "runs" / "1").mkdir()
    (c / "runs" / "1" / "stale.txt").write_text("X", encoding="utf-8")
    return c


def test_seed_copies_all_incl_review_record_skips_runs(tmp_path):
    c = _canonical(tmp_path)
    wd = tmp_path / "canonical" / "runs" / "2"
    wd.mkdir(parents=True)
    seed.run(wd, canonical=c)
    for rel in [
        "design.md",
        "manifest.json",
        "child_a.md",
        "spec-review.json",
        "constraints/m.sdc",
    ]:
        assert (wd / rel).read_text() == (c / rel).read_text(), rel
    assert not (wd / "runs").exists()  # prior run workdirs are never carried


def test_seed_no_clobber_keeps_fresh_work(tmp_path):
    c = _canonical(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "design.md").write_text("FRESH", encoding="utf-8")
    seed.run(wd, canonical=c)
    assert (wd / "design.md").read_text() == "FRESH"  # never overwritten
    assert (wd / "manifest.json").read_text() == "{}"  # still carried
