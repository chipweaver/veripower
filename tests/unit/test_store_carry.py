import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import store  # noqa: E402


def _canon(tmp_path, rule_root):
    c = tmp_path / "m" / rule_root
    c.mkdir(parents=True, exist_ok=True)
    return c


def test_author_carry_brings_products_drops_review_and_internals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _canon(tmp_path, "Design/specification")
    (c / "design.md").write_text("D")
    (c / "manifest.json").write_text("{}")
    (c / "constraints").mkdir()
    (c / "constraints" / "top.sdc").write_text("sdc")
    (c / "spec-review" / "findings").mkdir(parents=True, exist_ok=True)
    (c / "spec-review" / "findings" / "leaf.md").write_text("finding")  # no_carry
    (c / "spec-review" / "decisions.md").write_text("ruling")  # carries: the human's
    (c / "result.json").write_text("{}")  # framework-excluded
    (c / "dispatch.json").write_text("{}")  # kernel-scratch, defense-in-depth exclude
    (c / "runs").mkdir()
    (c / "runs" / "1").mkdir()
    (c / "runs" / "1" / "junk").write_text("j")  # excluded (runs/)
    wd = c / "runs" / "2"
    wd.mkdir()
    store.carry_self(store.module_root("m"), "specification", wd)
    assert (wd / "design.md").read_text() == "D"
    assert (wd / "manifest.json").exists()
    assert (wd / "constraints" / "top.sdc").exists()
    assert not (wd / "spec-review" / "findings" / "leaf.md").exists()  # no_carry
    # The ruling outlives the round it was made in: a later round that does not revisit it
    # must still deliver it, or the reap that promotes that round deletes it from canonical.
    assert (wd / "spec-review" / "decisions.md").read_text() == "ruling"
    assert not (wd / "result.json").exists()  # framework-excluded
    assert not (wd / "dispatch.json").exists()  # scratch
    assert not (wd / "junk").exists() and not (wd / "runs").exists()


def test_carry_is_copy_not_hardlink_and_writable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _canon(tmp_path, "Design/rtl-design")
    src = c / "top.v"
    src.write_text("module top; endmodule")
    wd = c / "runs" / "1"
    wd.mkdir(parents=True)
    wd.chmod(0o750)
    store.carry_self(store.module_root("m"), "rtl-design", wd)
    dst = wd / "top.v"
    assert os.stat(dst).st_ino != os.stat(src).st_ino  # copy, not hardlink
    assert os.access(dst, os.W_OK)  # 0644 writable
    assert wd.stat().st_mode & 0o777 == 0o750


@pytest.mark.parametrize(
    "stage", ["lint-cdc", "synthesis", "timing-analysis", "power-analysis"]
)
def test_tool_carry_preserves_published_setup_and_measurements(
    tmp_path, monkeypatch, stage
):
    monkeypatch.chdir(tmp_path)
    directory = "Verification" if stage == "power-analysis" else "Design"
    c = _canon(tmp_path, f"{directory}/{stage}")
    files = {
        "scripts/helper.tcl": "authored helper",
        "config.tcl": "source scripts/helper.tcl",
        "reports/measurement.txt": "measured under recorded conditions",
        "out/netlist.v": "module top; endmodule",
    }
    for name, content in files.items():
        p = c / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    (c / "result.json").write_text('{"status":"pass"}')
    (c / "dispatch.json").write_text("{}")
    wd = c / "runs" / "2"
    wd.mkdir(parents=True)
    store.carry_self(store.module_root("m"), stage, wd)
    for name, content in files.items():
        assert (wd / name).read_text() == content
        (wd / name).write_text("changed")
        assert (c / name).read_text() == content
    for excluded in ("result.json", "dispatch.json", "runs"):
        assert not (wd / excluded).exists()


def test_first_run_no_canonical_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "m" / "Design" / "specification" / "runs" / "1"
    wd.mkdir(parents=True)
    store.carry_self(
        store.module_root("m"), "specification", wd
    )  # canonical parent has only runs/
    assert list(wd.iterdir()) == []


def test_no_canonical_stage_dir_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m").mkdir(parents=True)  # module exists, Design/specification does not
    wd = tmp_path / "wd"
    wd.mkdir()
    store.carry_self(
        store.module_root("m"), "specification", wd
    )  # drives `not stage_dir.is_dir()` early return
    assert list(wd.iterdir()) == []


def test_external_file_link_becomes_writable_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _canon(tmp_path, "Design/specification")
    real = tmp_path / "external.md"
    real.write_text("external content")
    real.chmod(0o444)
    os.symlink(real, c / "linked.md")
    wd = c / "runs" / "1"
    wd.mkdir(parents=True)
    store.carry_self(store.module_root("m"), "specification", wd)
    assert not (wd / "linked.md").is_symlink()
    assert (wd / "linked.md").read_text() == "external content"
    (wd / "linked.md").write_text("new round")
    assert real.read_text() == "external content"
    assert real.stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize(
    "rule",
    [name for name, declaration in store.rules.RULES.items() if declaration.carry],
)
@pytest.mark.parametrize("absolute", [False, True])
def test_internal_aliases_survive_carry_and_edit_only_new_copy(
    tmp_path, rule, absolute
):
    root = tmp_path / "module with spaces"
    stage = root.joinpath(*store.rules.workdir_root(rule))
    real = stage / "products/data.txt"
    real.parent.mkdir(parents=True)
    real.write_text("before")
    alias = stage / "alias"
    alias.symlink_to(real.parent if absolute else "products", target_is_directory=True)
    (stage / "file.txt").symlink_to(real if absolute else "products/data.txt")
    (stage / "chain.txt").symlink_to("file.txt")
    (stage / "through-dir.txt").symlink_to("alias/data.txt")
    wd = stage / "runs/1"
    wd.mkdir(parents=True)
    store.carry_self(root, rule, wd)
    for name in ["alias/data.txt", "file.txt", "chain.txt", "through-dir.txt"]:
        assert (wd / name).read_text() == "before"
    (wd / "chain.txt").write_text("after")
    for name in ["products/data.txt", "alias/data.txt", "file.txt", "through-dir.txt"]:
        assert (wd / name).read_text() == "after"
    assert real.read_text() == "before"
    # The copy remains self-contained when moved away from the old stage.
    moved = tmp_path / "relocated"
    wd.rename(moved)
    assert (moved / "chain.txt").read_text() == "after"
    assert (moved / "alias/data.txt").read_text() == "after"


def test_external_directory_and_old_run_reference_are_materialized(tmp_path):
    root = tmp_path / "m"
    stage = root / "Design/synthesis"
    old = stage / "runs/1"
    old.mkdir(parents=True)
    (old / "netlist.v").write_text("old netlist")
    external = tmp_path / "external"
    external.mkdir()
    (external / "cell.lib").write_text("library")
    (external / "alias.lib").symlink_to("cell.lib")
    (external / "cell.lib").chmod(0o444)
    external.chmod(0o555)
    (stage / "library").symlink_to(external, target_is_directory=True)
    (stage / "netlist.v").symlink_to(old / "netlist.v")
    wd = stage / "runs/2"
    wd.mkdir()
    try:
        store.carry_self(root, "synthesis", wd)
        assert not (wd / "library").is_symlink()
        (wd / "library/cell.lib").write_text("new library")
        assert (wd / "library/alias.lib").is_symlink()
        assert (wd / "library/alias.lib").read_text() == "new library"
        (wd / "library/new.lib").write_text("added")
        (wd / "netlist.v").write_text("new netlist")
        assert (external / "cell.lib").read_text() == "library"
        assert not (external / "new.lib").exists()
        assert external.stat().st_mode & 0o777 == 0o555
        assert (old / "netlist.v").read_text() == "old netlist"
        assert not (wd / "runs").exists()
    finally:
        external.chmod(0o755)


def test_missing_reference_is_an_error_not_a_silent_omission(tmp_path):
    root = tmp_path / "m"
    stage = root / "Design/rtl-design"
    wd = stage / "runs/1"
    wd.mkdir(parents=True)
    (stage / "file.v").write_text("original")
    (stage / "alias.v").symlink_to("file.v")
    (stage / "missing.v").symlink_to(tmp_path / "absent.v")
    with pytest.raises(FileNotFoundError):
        store.carry_self(root, "rtl-design", wd)
    assert list(wd.iterdir()) == []
    assert list(wd.parent.iterdir()) == [wd]
    (tmp_path / "absent.v").write_text("repaired")
    store.carry_self(root, "rtl-design", wd)
    assert (wd / "alias.v").read_text() == "original"
    assert (wd / "missing.v").read_text() == "repaired"


@pytest.mark.parametrize("cycle", ["external", "stage"])
def test_materialization_does_not_recurse_through_its_source_or_destination(
    tmp_path, cycle
):
    root = tmp_path / "m"
    stage = root / "Design/synthesis"
    wd = stage / "runs/1"
    wd.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (other / "back").symlink_to(external, target_is_directory=True)
    target = other if cycle == "external" else stage
    (external / "back").symlink_to(target, target_is_directory=True)
    (stage / "linked").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="recursive directory reference"):
        store.carry_self(root, "synthesis", wd)
    assert list(wd.iterdir()) == []


def test_rtl_carry_starstar_includes_nested_and_sidecar_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = tmp_path / "m" / "Design" / "rtl-design"
    (c / "rtl").mkdir(parents=True)
    (c / "rtl" / "core.sv").write_text("s")  # nested HDL
    (c / "rtl-files.json").write_text("{}")  # authored sidecar
    (c / "constraint-annotations.json").write_text("{}")  # authored sidecar
    (c / "notes").mkdir(parents=True)
    (c / "notes" / "fsm.md").write_text("n")  # LLM-named support file
    (c / "semantic-review").mkdir(exist_ok=True)
    (c / "semantic-review" / "leaf.md").write_text("review")  # no_carry
    wd = c / "runs" / "1"
    wd.mkdir(parents=True)
    store.carry_self(store.module_root("m"), "rtl-design", wd)
    assert (wd / "rtl" / "core.sv").exists()
    assert (wd / "rtl-files.json").exists()
    assert (wd / "constraint-annotations.json").exists()
    assert (wd / "notes" / "fsm.md").exists()
    assert not (wd / "semantic-review" / "leaf.md").exists()


def test_carry_does_not_walk_run_history(tmp_path, monkeypatch):
    c = _canon(tmp_path, "Design/synthesis")
    (c / "reports").mkdir()
    (c / "reports/area.rpt").write_text("measurement")
    wd = c / "runs/2"
    wd.mkdir(parents=True)
    rglob = Path.rglob

    def traverse(path, pattern):
        assert path != c / "runs", "history is not a carry source"
        return rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", traverse)
    store.carry_self(tmp_path / "m", "synthesis", wd)
    assert (wd / "reports/area.rpt").read_text() == "measurement"
