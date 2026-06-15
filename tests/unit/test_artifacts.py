"""Tests for framework/scripts/artifacts.py — fs-lifecycle helpers.

Moved from test_state.py (TestPromoteAtomic + TestSubagentTraceMirror).
Imports the artifact functions from the artifacts module directly to verify
the module boundary; also imports state for cmd_init/cmd_start/cmd_complete
integration tests.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "framework" / "scripts"))

import artifacts
from conftest import bootstrap_prereqs_pass_clean, write_run_result

from framework.scripts import state


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
        state.cmd_init("foo")
        run_dir = state._result_path("foo", stage).parent / "runs" / str(run_n)
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
        artifacts.promote("foo", "lint-cdc", 1)
        canonical_rj = state._result_path("foo", "lint-cdc")
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
        artifacts.promote("foo", "lint-cdc", 1)
        canonical_dir = state._result_path("foo", "lint-cdc").parent / "reports"
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
        artifacts.promote("foo", "lint-cdc", 1)
        # run 2 with different content
        run2 = state._result_path("foo", "lint-cdc").parent / "runs" / "2"
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
        artifacts.promote("foo", "lint-cdc", 2)
        canonical_rj = state._result_path("foo", "lint-cdc")
        # canonical now reflects run 2
        assert canonical_rj.read_text() == (run2 / "result.json").read_text()
        assert (canonical_rj.parent / "report.txt").read_text() == "v2 content"

    def test_promote_replaces_non_empty_directory_artifact(self, tmp_path, monkeypatch):
        """second promote on a dir artifact must work
        (POSIX rename(2) on non-empty target returns ENOTEMPTY; need rmtree-then-rename)."""
        self._setup_run(tmp_path, monkeypatch, "lint-cdc", 1, dir_artifacts=["reports"])
        artifacts.promote("foo", "lint-cdc", 1)
        # run 2 with different content in reports/
        run2 = state._result_path("foo", "lint-cdc").parent / "runs" / "2"
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
        artifacts.promote("foo", "lint-cdc", 2)  # KEY: should not raise ENOTEMPTY
        canonical_dir = state._result_path("foo", "lint-cdc").parent / "reports"
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
        artifacts.promote("foo", "lint-cdc", 1)
        # run 2: artifact references non-existent file
        run2 = state._result_path("foo", "lint-cdc").parent / "runs" / "2"
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
            artifacts.promote("foo", "lint-cdc", 2)
        # canonical still reflects run 1 (run 1's produced_at is 00:00, run 2's 01:00)
        canonical_rj = state._result_path("foo", "lint-cdc")
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
        artifacts.promote("foo", "lint-cdc", 1)
        canonical_rj = state._result_path("foo", "lint-cdc")
        assert canonical_rj.exists()
        # Single link — canonical result.json IS the run's result.json (same inode).
        assert canonical_rj.stat().st_ino == (run_dir / "result.json").stat().st_ino

    def test_promote_symlink_does_not_traverse(self, tmp_path, monkeypatch):
        """_cp_al must not follow dir-symlinks during
        recursive copy (would cause traversal outside runs/<N>/).
        Symlinks are hardlinked at the symlink level (preserved as-is).
        """
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # Set up an external dir outside runs/
        external = tmp_path / "external_dir"
        external.mkdir()
        (external / "should_not_traverse.txt").write_text("EXTERNAL")
        # Create a run with a symlinked dir artifact pointing outside
        run_dir = state._result_path("foo", "lint-cdc").parent / "runs" / "1"
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
        artifacts.promote("foo", "lint-cdc", 1)
        # canonical/real_dir/child.txt copied (hardlink)
        canonical = state._result_path("foo", "lint-cdc").parent
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


class TestSubagentTraceMirror:
    """T-11: _mirror_subagent_trace copies /tmp async transcripts into workdir."""

    def test_happy_path_copies_to_workdir_subagent_traces(self, tmp_path):
        # source: simulate Claude Code /tmp transcript
        src_dir = tmp_path / "claude-1001" / "wd-enc" / "uuid" / "tasks"
        src_dir.mkdir(parents=True)
        agent_id = "a1234567890abcdef"
        src = src_dir / f"{agent_id}.output"
        src.write_text('{"role":"assistant","content":"hello"}\n')

        workdir = (
            tmp_path / "asic" / "foo" / "Verification" / "simulation" / "runs" / "1"
        )
        workdir.mkdir(parents=True)

        dst = artifacts._mirror_subagent_trace(workdir, "simulation", str(src))
        assert dst is not None
        assert dst == workdir / ".subagent_traces" / f"simulation-{agent_id}.output"
        assert dst.exists()
        assert dst.read_text() == src.read_text()

    def test_missing_source_returns_none_silently(self, tmp_path):
        workdir = (
            tmp_path / "asic" / "foo" / "Verification" / "simulation" / "runs" / "1"
        )
        workdir.mkdir(parents=True)
        result = artifacts._mirror_subagent_trace(
            workdir,
            "simulation",
            str(tmp_path / "nonexistent" / "a000.output"),
        )
        assert result is None
        assert not (workdir / ".subagent_traces").exists()

    def test_none_output_file_skips(self, tmp_path):
        workdir = (
            tmp_path / "asic" / "foo" / "Verification" / "simulation" / "runs" / "1"
        )
        workdir.mkdir(parents=True)
        assert artifacts._mirror_subagent_trace(workdir, "simulation", None) is None
        assert not (workdir / ".subagent_traces").exists()

    def test_empty_output_file_skips(self, tmp_path):
        workdir = (
            tmp_path / "asic" / "foo" / "Verification" / "simulation" / "runs" / "1"
        )
        workdir.mkdir(parents=True)
        assert artifacts._mirror_subagent_trace(workdir, "simulation", "") is None
        assert not (workdir / ".subagent_traces").exists()

    def test_cmd_complete_backward_compat_no_subagent_output_file(
        self, tmp_path, monkeypatch
    ):
        """Existing callers that do not pass --subagent-output-file must still work."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        bootstrap_prereqs_pass_clean("foo", "specification")
        result = state.cmd_start("foo", "specification")
        run_n = result["run"]
        write_run_result("foo", "specification", run_n)

        # no subagent_output_file kwarg — must not raise
        resp = state.cmd_complete("foo", "specification", run=run_n, outcome="pass")
        assert resp.get("action") == "completed"
        assert resp.get("result_status") == "pass"
        # no .subagent_traces created (None output_file path)
        workdir = (
            state._result_path("foo", "specification").parent / "runs" / str(run_n)
        )
        assert not (workdir / ".subagent_traces").exists()

    def test_oserror_returns_none_and_writes_stderr(
        self, tmp_path, monkeypatch, capsys
    ):
        """OSError on copy (permission denied / disk full / mkdir failure) must
        not abort the caller — best-effort contract per docstring 'Never raises'.

        Covers the except OSError branch: helper logs to stderr and returns None
        so the cmd_complete reap path continues uninterrupted.
        """
        src_dir = tmp_path / "claude-1001" / "wd-enc" / "uuid" / "tasks"
        src_dir.mkdir(parents=True)
        agent_id = "a1234567890abcdef"
        src = src_dir / f"{agent_id}.output"
        src.write_text('{"role":"assistant"}\n')

        workdir = (
            tmp_path / "asic" / "foo" / "Verification" / "simulation" / "runs" / "1"
        )
        workdir.mkdir(parents=True)

        # Force shutil.copy2 to raise PermissionError (representative OSError subclass)
        def _raise(_src, _dst):
            raise PermissionError("simulated permission denied")

        monkeypatch.setattr(artifacts.shutil, "copy2", _raise)

        result = artifacts._mirror_subagent_trace(workdir, "simulation", str(src))
        assert result is None
        # stderr carries diagnostic with stage + agent_id (operator-visible)
        captured = capsys.readouterr()
        assert "mirror subagent trace failed" in captured.err
        assert "stage=simulation" in captured.err
        assert agent_id in captured.err
        # .subagent_traces/ dir is created (mkdir succeeded before copy), but
        # no transcript file inside — the missing copy is the only effect
        assert (workdir / ".subagent_traces").exists()
        assert not (
            workdir / ".subagent_traces" / f"simulation-{agent_id}.output"
        ).exists()

    def test_cmd_complete_forwards_subagent_output_file(self, tmp_path, monkeypatch):
        """End-to-end: cmd_complete with subagent_output_file mirrors the
        transcript into <workdir>/.subagent_traces/ during the reap path.

        Complements the 4 helper-level cases above (happy / missing / None /
        empty) by verifying the cmd_complete integration: the new kwarg
        actually flows through to _mirror_subagent_trace and lands the file.
        """
        monkeypatch.chdir(tmp_path)
        # Set up a /tmp-style transcript outside the module workspace
        src_dir = tmp_path / "claude-1001" / "wd-enc" / "uuid" / "tasks"
        src_dir.mkdir(parents=True)
        agent_id = "b0123456789abcdef"
        src = src_dir / f"{agent_id}.output"
        src.write_text('{"role":"assistant","content":"sim run"}\n')

        state.cmd_init("foo")
        bootstrap_prereqs_pass_clean("foo", "specification")
        result = state.cmd_start("foo", "specification")
        run_n = result["run"]
        write_run_result("foo", "specification", run_n)

        resp = state.cmd_complete(
            "foo",
            "specification",
            run=run_n,
            outcome="pass",
            subagent_output_file=str(src),
        )
        assert resp.get("action") == "completed"

        workdir = (
            state._result_path("foo", "specification").parent / "runs" / str(run_n)
        )
        mirrored = workdir / ".subagent_traces" / f"specification-{agent_id}.output"
        assert mirrored.exists(), f"trace mirror missing at {mirrored}"
        assert mirrored.read_text() == src.read_text()
