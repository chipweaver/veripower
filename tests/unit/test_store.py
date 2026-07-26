"""Tests for framework/scripts/store.py — fs-lifecycle helpers.

Moved from test_state.py (TestPromoteAtomic + TestSubagentTraceMirror).
Imports the store functions from the store module directly to verify
the module boundary.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "framework" / "scripts"))

import store


class TestPromoteAtomic:
    def _setup_run(
        self,
        tmp_path,
        monkeypatch,
        stage,
        run_n,
        artifacts_list=None,
        dir_artifacts=None,
    ):
        """Set up a run dir with result.json + optional file/dir artifacts.
        Returns (run_dir)."""
        monkeypatch.chdir(tmp_path)
        run_dir = store._result_path("foo", stage).parent / "runs" / str(run_n)
        run_dir.mkdir(parents=True)
        if artifacts_list is None:
            artifacts_list = []
        if dir_artifacts is None:
            dir_artifacts = []
        # Create file artifacts
        for path in artifacts_list:
            (run_dir / path).parent.mkdir(parents=True, exist_ok=True)
            (run_dir / path).write_text(f"content of {path}")
        # Create dir artifacts (non-empty subdirs)
        for path in dir_artifacts:
            d = run_dir / path
            d.mkdir(parents=True, exist_ok=True)
            (d / "child.txt").write_text(f"child of {path}")
        # All artifact paths declared in result.json
        all_artifacts = [{"path": p} for p in (artifacts_list + dir_artifacts)]
        rj = {
            "schema_version": 1,
            "stage": stage,
            "module": "foo",
            "produced_at": "2026-04-27T00:00:00Z",
            "status": "pass",
            "artifacts": all_artifacts,
            "stage_specific": {},
        }
        # specification/synthesis/etc may need stage_specific match — use lint-cdc for simplicity:
        if stage == "lint-cdc":
            rj["stage_specific"] = {"violations": []}
        (run_dir / "result.json").write_text(json.dumps(rj))
        return run_dir

    def test_promote_creates_canonical_view(self, tmp_path, monkeypatch):
        """Promote run → canonical has hardlinks to result.json + artifacts."""
        run_dir = self._setup_run(
            tmp_path, monkeypatch, "lint-cdc", 1, artifacts_list=["report.txt"]
        )
        store.promote("foo", "lint-cdc", 1)
        canonical_rj = store._result_path("foo", "lint-cdc")
        canonical_artifact = canonical_rj.parent / "report.txt"
        assert canonical_rj.exists()
        assert canonical_artifact.exists()
        # hardlink: same inode
        assert canonical_rj.stat().st_ino == (run_dir / "result.json").stat().st_ino
        assert (
            canonical_artifact.stat().st_ino == (run_dir / "report.txt").stat().st_ino
        )

    def test_promote_handles_directory_artifact(self, tmp_path, monkeypatch):
        """directory artifacts must work via cp_al
        (tree hardlinks)."""
        run_dir = self._setup_run(
            tmp_path, monkeypatch, "lint-cdc", 1, dir_artifacts=["reports"]
        )
        store.promote("foo", "lint-cdc", 1)
        canonical_dir = store._result_path("foo", "lint-cdc").parent / "reports"
        assert canonical_dir.is_dir()
        assert (canonical_dir / "child.txt").exists()
        assert (canonical_dir / "child.txt").stat().st_ino == (
            run_dir / "reports" / "child.txt"
        ).stat().st_ino

    def test_promote_replaces_old_canonical(self, tmp_path, monkeypatch):
        """Run 2 promote replaces run 1's canonical view (file artifact)."""
        self._setup_run(
            tmp_path, monkeypatch, "lint-cdc", 1, artifacts_list=["report.txt"]
        )
        store.promote("foo", "lint-cdc", 1)
        # run 2 with different content
        run2 = store._result_path("foo", "lint-cdc").parent / "runs" / "2"
        run2.mkdir()
        (run2 / "report.txt").write_text("v2 content")
        rj = {
            "schema_version": 1,
            "stage": "lint-cdc",
            "module": "foo",
            "produced_at": "2026-04-27T01:00:00Z",
            "status": "pass",
            "artifacts": [{"path": "report.txt"}],
            "stage_specific": {"violations": []},
        }
        (run2 / "result.json").write_text(json.dumps(rj))
        store.promote("foo", "lint-cdc", 2)
        canonical_rj = store._result_path("foo", "lint-cdc")
        # canonical now reflects run 2
        assert canonical_rj.read_text() == (run2 / "result.json").read_text()
        assert (canonical_rj.parent / "report.txt").read_text() == "v2 content"

    def test_promote_replaces_non_empty_directory_artifact(self, tmp_path, monkeypatch):
        """second promote on a dir artifact must work
        (POSIX rename(2) on non-empty target returns ENOTEMPTY; need rmtree-then-rename)."""
        self._setup_run(tmp_path, monkeypatch, "lint-cdc", 1, dir_artifacts=["reports"])
        store.promote("foo", "lint-cdc", 1)
        # run 2 with different content in reports/
        run2 = store._result_path("foo", "lint-cdc").parent / "runs" / "2"
        run2.mkdir()
        (run2 / "reports").mkdir()
        (run2 / "reports" / "v2-area.txt").write_text("v2 area report")
        (run2 / "reports" / "v2-timing.txt").write_text("v2 timing report")
        rj = {
            "schema_version": 1,
            "stage": "lint-cdc",
            "module": "foo",
            "produced_at": "2026-04-27T01:00:00Z",
            "status": "pass",
            "artifacts": [{"path": "reports"}],
            "stage_specific": {"violations": []},
        }
        (run2 / "result.json").write_text(json.dumps(rj))
        store.promote("foo", "lint-cdc", 2)  # KEY: should not raise ENOTEMPTY
        canonical_dir = store._result_path("foo", "lint-cdc").parent / "reports"
        # canonical reports/ now reflects run 2 (v1 child.txt gone, v2 files present)
        assert (canonical_dir / "v2-area.txt").exists()
        assert (canonical_dir / "v2-timing.txt").exists()
        # child.txt is not in canonical
        assert not (canonical_dir / "child.txt").exists()

    def test_promote_failure_leaves_canonical_intact(self, tmp_path, monkeypatch):
        """promote step 1 failure (e.g., missing artifact) → .promote-tmp cleared,
        canonical fully intact."""
        self._setup_run(
            tmp_path, monkeypatch, "lint-cdc", 1, artifacts_list=["report.txt"]
        )
        store.promote("foo", "lint-cdc", 1)
        # run 2: artifact references non-existent file
        run2 = store._result_path("foo", "lint-cdc").parent / "runs" / "2"
        run2.mkdir()
        rj = {
            "schema_version": 1,
            "stage": "lint-cdc",
            "module": "foo",
            "produced_at": "2026-04-27T01:00:00Z",
            "status": "pass",
            "artifacts": [{"path": "missing-artifact.txt"}],
            "stage_specific": {"violations": []},
        }
        (run2 / "result.json").write_text(json.dumps(rj))
        # promote should raise
        with pytest.raises((FileNotFoundError, OSError)):
            store.promote("foo", "lint-cdc", 2)
        # canonical still reflects run 1 (run 1's produced_at is 00:00, run 2's 01:00)
        canonical_rj = store._result_path("foo", "lint-cdc")
        canonical_data = json.loads(canonical_rj.read_text())
        assert canonical_data["produced_at"] == "2026-04-27T00:00:00Z"
        # .promote-tmp cleaned up
        assert not (canonical_rj.parent / ".promote-tmp").exists()

    def test_promote_skips_self_listed_result_json(self, tmp_path, monkeypatch):
        """A producer that self-lists result.json in artifacts[] must NOT crash
        promote with FileExistsError — result.json is already hardlinked at the
        top of the canonical view. Regression for the 11x promote_failed churn
        in the sdc_controller-20260529 run."""
        run_dir = self._setup_run(
            tmp_path, monkeypatch, "lint-cdc", 1, artifacts_list=["result.json"]
        )
        # Must not raise FileExistsError.
        store.promote("foo", "lint-cdc", 1)
        canonical_rj = store._result_path("foo", "lint-cdc")
        assert canonical_rj.exists()
        # Single link — canonical result.json IS the run's result.json (same inode).
        assert canonical_rj.stat().st_ino == (run_dir / "result.json").stat().st_ino

    @pytest.mark.parametrize(
        "bad_path", ["../escape.txt", "/etc/escape.txt", "sub/../../escape.txt", ".."]
    )
    def test_promote_rejects_traversal_path(self, tmp_path, monkeypatch, bad_path):
        """Defense-in-depth: promote() itself rejects an artifacts[] path that
        escapes runs/<N>/ (lexically), even though validate_result also rejects it
        upstream. Mirrors the self-listing primitive guard in promote()."""
        run_dir = self._setup_run(tmp_path, monkeypatch, "lint-cdc", 1)
        rj = run_dir / "result.json"
        data = json.loads(rj.read_text())
        data["artifacts"] = [{"path": bad_path}]
        rj.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="escapes run dir"):
            store.promote("foo", "lint-cdc", 1)
        # tmp cleaned up by the except-handler; canonical untouched
        assert not (
            store._result_path("foo", "lint-cdc").parent / ".promote-tmp"
        ).exists()

    def test_promote_symlink_does_not_traverse(self, tmp_path, monkeypatch):
        """_cp_al must not follow dir-symlinks during
        recursive copy (would cause traversal outside runs/<N>/).
        Symlinks are hardlinked at the symlink level (preserved as-is).
        """
        monkeypatch.chdir(tmp_path)
        # Set up an external dir outside runs/
        external = tmp_path / "external_dir"
        external.mkdir()
        (external / "should_not_traverse.txt").write_text("EXTERNAL")
        # Create a run with a symlinked dir artifact pointing outside
        run_dir = store._result_path("foo", "lint-cdc").parent / "runs" / "1"
        run_dir.mkdir(parents=True)
        (run_dir / "real_dir").mkdir()
        (run_dir / "real_dir" / "child.txt").write_text("inside")
        # symlink: run_dir/symlink_to_external → external
        os.symlink(str(external), str(run_dir / "symlink_to_external"))
        rj = {
            "schema_version": 1,
            "stage": "lint-cdc",
            "module": "foo",
            "produced_at": "2026-04-27",
            "status": "pass",
            "artifacts": [{"path": "real_dir"}, {"path": "symlink_to_external"}],
            "stage_specific": {"violations": []},
        }
        (run_dir / "result.json").write_text(json.dumps(rj))
        # promote should succeed without traversing into external/
        store.promote("foo", "lint-cdc", 1)
        # canonical/real_dir/child.txt copied (hardlink)
        canonical = store._result_path("foo", "lint-cdc").parent
        assert (canonical / "real_dir" / "child.txt").exists()
        # canonical/symlink_to_external is a symlink (preserved as-is, not traversed)
        sym = canonical / "symlink_to_external"
        assert sym.is_symlink()
        # Must NOT have copied external/should_not_traverse.txt into canonical
        import shutil

        shutil.rmtree(str(external))
        # symlink still exists (we hardlinked the symlink itself)
        assert sym.is_symlink()
        # but cannot follow it now (proves we didn't copy content)
        assert not (sym / "should_not_traverse.txt").exists()
