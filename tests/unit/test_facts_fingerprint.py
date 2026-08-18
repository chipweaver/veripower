import os
import sys
from pathlib import Path

import pytest

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


def test_cache_file_is_parsed_at_most_once_per_process(tmp_path, monkeypatch):
    # One `kernel.py status` makes ~80 fingerprint_cached calls over ~40 distinct paths.
    # Parsing the whole cache per call costs more than the sha256 it saves on a small
    # artifact, so the parse happens once and later calls hit the in-memory dict.
    for name in ("a.v", "b.v"):
        (tmp_path / name).write_text(name)
    facts._LOADED.pop(str(tmp_path), None)
    reads = []
    orig_read = Path.read_text

    def counting_read(self, *a, **k):
        reads.append(self.name)
        return orig_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", counting_read)
    for _ in range(4):
        for name in ("a.v", "b.v"):
            facts.fingerprint_cached(tmp_path / name, tmp_path)
    assert reads.count(".fingerprint-cache.json") == 1


def test_cache_survives_across_processes(tmp_path, monkeypatch):
    # The disk file is what lets the next kernel invocation skip re-hashing a large netlist
    # or SDF, so a fresh process must hit on what this one wrote.
    f = tmp_path / "a.v"
    f.write_text("module a; endmodule\n")
    fp = facts.fingerprint_cached(f, tmp_path)
    facts._LOADED.clear()  # a fresh process: memo empty, disk file intact

    def refuse(_path):
        raise AssertionError(
            "re-hashed a file the previous process already fingerprinted"
        )

    monkeypatch.setattr(facts, "fingerprint", refuse)
    assert facts.fingerprint_cached(f, tmp_path) == fp


def test_cached_symlink_not_followed_and_no_collision(tmp_path):
    # file-first then link
    root = tmp_path / "r1"
    root.mkdir()
    target = root / "target.txt"
    target.write_text("AAAA")
    lnk = root / "lnk"
    os.symlink("target.txt", lnk)
    fp_file = facts.fingerprint_cached(target, root)
    fp_link = facts.fingerprint_cached(lnk, root)
    assert fp_file == facts.fingerprint(target)
    assert fp_link == facts.fingerprint(lnk)
    assert fp_link != fp_file
    # fresh root, link-first then file
    root2 = tmp_path / "r2"
    root2.mkdir()
    target2 = root2 / "target.txt"
    target2.write_text("AAAA")
    lnk2 = root2 / "lnk"
    os.symlink("target.txt", lnk2)
    fp_link2 = facts.fingerprint_cached(lnk2, root2)
    fp_file2 = facts.fingerprint_cached(target2, root2)
    assert fp_link2 == facts.fingerprint(lnk2)
    assert fp_file2 == facts.fingerprint(target2)
    assert fp_link2 != fp_file2


def test_cached_dir_reflects_nested_edit(tmp_path):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    f = d / "sub" / "f.txt"
    f.write_text("before")
    fp1 = facts.fingerprint_cached(d, tmp_path)
    # editing the nested file does NOT change d's own mtime
    f.write_text("after-edit")
    fp2 = facts.fingerprint_cached(d, tmp_path)
    assert fp2 != fp1
    assert fp2 == facts.fingerprint(d)


@pytest.mark.skipif(os.geteuid() == 0, reason="permissions ineffective as root")
def test_cached_unreadable_parent_returns_unknown(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    f = locked / "f.txt"
    f.write_text("secret")
    locked.chmod(0o000)
    try:
        assert facts.fingerprint_cached(f, tmp_path) == facts.UNKNOWN
    finally:
        locked.chmod(0o755)  # restore so tmp cleanup works


@pytest.mark.parametrize(
    "payload",
    [
        "[1, 2, 3]",  # list root -> cache.get() AttributeError
        '"just-a-string"',  # str root -> cache.get() AttributeError
        "42",  # int root -> cache.get() AttributeError
        '{"Design/x.v": 5}',  # int entry -> hit[0] TypeError
        '{"Design/x.v": "s"}',  # str entry
        '{"Design/x.v": [1, 2]}',  # short-tuple entry
    ],
)
def test_corrupt_shape_fingerprint_cache_recomputes_not_crashes(tmp_path, payload):
    # The fingerprint cache is a PURE speed cache — "损坏 → 删了重算",
    # "删除只影响速度，不影响任何结论". A cache file that is valid JSON but the WRONG SHAPE
    # (list/str/int root, or a non-[size,mtime,fp] entry) must be treated as corrupt and
    # recomputed, never crash a kernel verb with AttributeError/TypeError/IndexError.
    f = tmp_path / "Design" / "x.v"
    f.parent.mkdir(parents=True)
    f.write_text("module x; endmodule\n")
    (tmp_path / ".fingerprint-cache.json").write_text(payload)
    assert facts.fingerprint_cached(f, tmp_path) == facts.fingerprint(f)
