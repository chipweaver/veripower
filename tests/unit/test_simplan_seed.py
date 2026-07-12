"""simplan seed — whitelist no-clobber carry of prior canonical PRODUCTS; adjudication
artifacts (result.json / plan-data.json) are never seeded, and the judged
plan-review.json is carried only under freeze=True (room-birth hygiene, §7.2)."""

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
    assert not (wd / "plan-review.json").exists()  # review carried only on freeze
    assert not (wd / "runs").exists()  # prior run workdirs are never carried


def test_seed_freeze_additionally_carries_review_record(tmp_path):
    c = _canonical(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    seed.run(wd, canonical=c, freeze=True)
    assert (wd / "plan-review.json").read_text() == '{"pin":1}'  # byte-carry keeps pin
    assert not (wd / "result.json").exists()  # never, even on freeze


def test_seed_no_clobber_keeps_fresh_work(tmp_path):
    c = _canonical(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "verification-plan.md").write_text("FRESH", encoding="utf-8")
    seed.run(wd, canonical=c)
    assert (wd / "verification-plan.md").read_text() == "FRESH"  # never overwritten
    assert (wd / "scaffold-specification.json").read_text() == "{}"  # still carried


# ── freeze-carry verification (closes the check-then-copy window) ────────────
def _canonical_with_digest(tmp_path):
    import json as _json

    from simplan.classify import products_digest

    c = _canonical(tmp_path)
    arts = ["verification-plan.md", "scaffold-specification.json", "plan-review.json"]
    (c / "result.json").write_text(
        _json.dumps(
            {
                "status": "pass",
                "stage_specific": {"products_digest": products_digest(c, arts)},
                "artifacts": [{"path": p} for p in arts],
            }
        ),
        encoding="utf-8",
    )
    return c


def test_seed_freeze_verifies_carried_bytes_ok(tmp_path):
    c = _canonical_with_digest(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    assert seed.run(wd, canonical=c, freeze=True) == 0


def test_seed_freeze_rejects_midrun_drift(tmp_path):
    # canonical edited AFTER the digest was recorded (i.e. after classify-delta said
    # freeze): the carried bytes no longer match — the freeze must not proceed
    c = _canonical_with_digest(tmp_path)
    (c / "verification-plan.md").write_text("TAMPERED", encoding="utf-8")
    wd = tmp_path / "wd"
    wd.mkdir()
    assert seed.run(wd, canonical=c, freeze=True) == 2


def test_seed_freeze_rejects_workdir_residue(tmp_path):
    # no-clobber keeps residue, so the carried set is not the canonical bytes —
    # verification enforces the freeze branch's empty-workdir premise mechanically
    c = _canonical_with_digest(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "verification-plan.md").write_text("RESIDUE", encoding="utf-8")
    assert seed.run(wd, canonical=c, freeze=True) == 2


def test_seed_freeze_legacy_canonical_skips_verification(tmp_path):
    # _canonical() writes a result.json with no products_digest (legacy baseline):
    # verification is skipped — classify-delta already refuses to freeze it
    c = _canonical(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    assert seed.run(wd, canonical=c, freeze=True) == 0
