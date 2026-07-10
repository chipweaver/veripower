import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import facts  # noqa: E402


def test_file_fingerprint_deterministic(tmp_path):
    f = tmp_path / "a.v"
    f.write_text("module a; endmodule\n")
    fp1 = facts.fingerprint(f)
    fp2 = facts.fingerprint(f)
    assert fp1 == fp2 and fp1.startswith("sha256:")


def test_file_fingerprint_changes_with_content(tmp_path):
    f = tmp_path / "a.v"
    f.write_text("x")
    a = facts.fingerprint(f)
    f.write_text("y")
    assert facts.fingerprint(f) != a


def test_dir_merkle_order_independent(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "b.txt").write_text("2")
    (d / "a.txt").write_text("1")
    fp = facts.fingerprint(d)
    # rewrite in different creation order, same content -> same merkle
    d2 = tmp_path / "d2"
    d2.mkdir()
    (d2 / "a.txt").write_text("1")
    (d2 / "b.txt").write_text("2")
    assert facts.fingerprint(d2) == fp and fp.startswith("merkle:")


def test_symlink_hashed_by_target_not_followed(tmp_path):
    (tmp_path / "real").write_text("payload")
    link = tmp_path / "lnk"
    os.symlink("real", link)
    fp_target_a = facts.fingerprint(link)
    os.remove(link)
    os.symlink("other", link)  # different target string, dangling
    assert facts.fingerprint(link) != fp_target_a  # target string participates


def test_missing_is_unknown_and_never_matches(tmp_path):
    assert facts.fingerprint(tmp_path / "nope") == facts.UNKNOWN
    assert not facts.versions_match(facts.UNKNOWN, facts.UNKNOWN)
    assert not facts.versions_match("sha256:x", facts.UNKNOWN)
    assert facts.versions_match("sha256:x", "sha256:x")


def test_cache_roundtrip_and_invalidation(tmp_path):
    f = tmp_path / "a.v"
    f.write_text("one")
    fp1 = facts.fingerprint_cached(f, tmp_path)
    assert (tmp_path / ".fingerprint-cache.json").exists()
    assert facts.fingerprint_cached(f, tmp_path) == fp1  # cache hit, same value
    f.write_text("twotwotwo")  # size + mtime change -> recompute
    assert facts.fingerprint_cached(f, tmp_path) != fp1
