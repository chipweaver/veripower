import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import store  # noqa: E402


def _canon(tmp_path, rule_root):
    c = tmp_path / "asic" / "m" / rule_root
    c.mkdir(parents=True, exist_ok=True)
    return c


def test_author_carry_brings_products_drops_review_and_internals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _canon(tmp_path, "Design/specification")
    (c / "design.md").write_text("D")
    (c / "manifest.json").write_text("{}")
    (c / "constraints").mkdir()
    (c / "constraints" / "top.sdc").write_text("sdc")
    (c / "spec-review.json").write_text("{}")  # no_carry
    (c / "result.json").write_text("{}")  # framework-excluded
    (c / "inputs.json").write_text("{}")  # kernel-scratch, defense-in-depth exclude
    (c / "directive.md").write_text("d")  # kernel-scratch, defense-in-depth exclude
    (c / "runs").mkdir()
    (c / "runs" / "1").mkdir()
    (c / "runs" / "1" / "junk").write_text("j")  # excluded (runs/)
    wd = c / "runs" / "2"
    wd.mkdir()
    store.carry_self("m", "specification", wd)
    assert (wd / "design.md").read_text() == "D"
    assert (wd / "manifest.json").exists()
    assert (wd / "constraints" / "top.sdc").exists()
    assert not (wd / "spec-review.json").exists()  # no_carry
    assert not (wd / "result.json").exists()  # framework-excluded
    assert (
        not (wd / "inputs.json").exists() and not (wd / "directive.md").exists()
    )  # scratch
    assert not (wd / "junk").exists() and not (wd / "runs").exists()


def test_carry_is_copy_not_hardlink_and_writable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _canon(tmp_path, "Design/rtl-design")
    src = c / "top.v"
    src.write_text("module top; endmodule")
    wd = c / "runs" / "1"
    wd.mkdir(parents=True)
    store.carry_self("m", "rtl-design", wd)
    dst = wd / "top.v"
    assert os.stat(dst).st_ino != os.stat(src).st_ino  # copy, not hardlink
    assert os.access(dst, os.W_OK)  # 0644 writable


def test_lint_carry_only_the_two_scripts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _canon(tmp_path, "Design/lint-cdc")
    (c / "scripts").mkdir()
    (c / "scripts" / "waiver.tcl").write_text("w")
    (c / "scripts" / "constraints.sgdc").write_text("s")
    (c / "scripts" / "filelist.txt").write_text("f")  # NOT in carry globs
    (c / "lint-report.txt").write_text("r")  # NOT in carry globs
    wd = c / "runs" / "1"
    wd.mkdir(parents=True)
    store.carry_self("m", "lint-cdc", wd)
    assert (wd / "scripts" / "waiver.tcl").exists()
    assert (wd / "scripts" / "constraints.sgdc").exists()
    assert not (wd / "scripts" / "filelist.txt").exists()
    assert not (wd / "lint-report.txt").exists()


def test_first_run_no_canonical_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Design" / "specification" / "runs" / "1"
    wd.mkdir(parents=True)
    store.carry_self("m", "specification", wd)  # canonical parent has only runs/
    assert list(wd.iterdir()) == []


def test_transformer_carry_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _canon(tmp_path, "Design/synthesis")
    (c / "constraints.sdc").write_text("s")
    wd = c / "runs" / "1"
    wd.mkdir(parents=True)
    store.carry_self("m", "synthesis", wd)  # carry=()
    assert list(wd.iterdir()) == []
