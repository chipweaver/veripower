"""simplan seed — whitelist no-clobber carry of prior canonical PRODUCTS; adjudication
artifacts (result.json / plan-data.json / the judged plan-review.json) are never
seeded (room-birth hygiene, §7.2)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills/simulation-plan/scripts"))
from simplan import seed  # noqa: E402


def _canonical(tmp_path):
    c = tmp_path / "canonical"
    c.mkdir(parents=True)
    (c / "verification-plan.md").write_text("D", encoding="utf-8")
    (c / "scaffold-specification.json").write_text("{}", encoding="utf-8")
    (c / "plan-review.json").write_text('{"pin":1}', encoding="utf-8")
    # never carried: the envelope and the every-branch re-derived plan data
    (c / "result.json").write_text('{"status":"pass"}', encoding="utf-8")
    (c / "plan-data.json").write_text("{}", encoding="utf-8")
    (c / "runs").mkdir()
    (c / "runs" / "1").mkdir()
    (c / "runs" / "1" / "stale.txt").write_text("X", encoding="utf-8")
    return c


def test_seed_carries_products_never_adjudication(tmp_path):
    c = _canonical(tmp_path)
    wd = tmp_path / "canonical" / "runs" / "2"
    wd.mkdir(parents=True)
    seed.run(wd, canonical=c)
    for rel in ["verification-plan.md", "scaffold-specification.json"]:
        assert (wd / rel).read_text() == (c / rel).read_text(), rel
    assert not (wd / "result.json").exists()
    assert not (wd / "plan-data.json").exists()
    assert not (wd / "plan-review.json").exists()  # judged review is never carried
    assert not (wd / "runs").exists()  # prior run workdirs are never carried


def test_seed_no_clobber_keeps_fresh_work(tmp_path):
    c = _canonical(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "verification-plan.md").write_text("FRESH", encoding="utf-8")
    seed.run(wd, canonical=c)
    assert (wd / "verification-plan.md").read_text() == "FRESH"  # never overwritten
    assert (wd / "scaffold-specification.json").read_text() == "{}"  # still carried
