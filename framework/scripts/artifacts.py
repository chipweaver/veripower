"""VeriPower filesystem artifact-lifecycle helpers.

Moved out of state.py so state.py stays focused on state mutations. No I/O
beyond the promote/mirror operations themselves. Imports only stdlib + the
_result_path helper from topology (no jsonschema/referencing deps).

Re-exported from state.py so existing `state.promote` / `state._mirror_subagent_trace`
/ `state.repair_partial_promote_if_needed` references keep resolving — same
pattern as topology.py.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from topology import _result_path


def _cp_al(src: Path, dst: Path) -> None:
    """Tree hardlink (cp -al equivalent). Recreates dir structure with hardlinks.

    Symlinks (whether to files or directories) are hardlinked at the symlink
    level — i.e., the destination becomes a second hardlink to the same
    symlink inode. This prevents unintended traversal outside the source
    tree (a symlink-to-directory pointing to /etc would otherwise be
    recursed into). The symlink itself is preserved as-is.
    """
    if dst.exists():
        raise FileExistsError(f"_cp_al dst exists: {dst}")
    dst.mkdir()
    for entry in src.iterdir():
        if entry.is_symlink():
            # Hardlink the symlink inode itself (follow_symlinks=False) so the
            # destination is a new hardlink to the same symlink — preserving it
            # as-is rather than resolving and traversing the target directory.
            os.link(str(entry), str(dst / entry.name), follow_symlinks=False)
        elif entry.is_dir():
            _cp_al(entry, dst / entry.name)
        else:
            os.link(str(entry), str(dst / entry.name))


def _mirror_subagent_trace(
    workdir: Path, stage: str, output_file: str | None
) -> Path | None:
    """Best-effort mirror of an async subagent transcript into workdir.

    Async Task launch produces an /tmp/.../tasks/<agent_id>.output JSONL
    transcript that gets garbage-collected by Claude Code at session end,
    leaving stage trace permanently unavailable for downstream analysis
    (external analysis / postmortem). Orchestrator forwards the value of
    the notification's <output-file> tag via --subagent-output-file on the
    reap state.py reap call; this helper copies it to a stable workdir
    relative path so the trace outlives the session.

    Destination: <workdir>/.subagent_traces/<stage>-<agent_id>.output
    (agent_id derived from src basename minus .output)

    Returns the destination path on success, or None on any skip / failure
    (missing source, empty arg, OSError). Never raises — caller is in the
    cmd_reap reap path and must not be aborted by trace-mirror issues.
    """
    if not output_file:
        return None
    src = Path(output_file)
    if not src.exists():
        return None
    agent_id = src.stem  # basename minus .output suffix
    dst_dir = workdir / ".subagent_traces"
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"{stage}-{agent_id}.output"
        shutil.copy2(src, dst)
        return dst
    except OSError as e:
        print(
            f"[state.py] mirror subagent trace failed "
            f"(stage={stage}, agent_id={agent_id}): {e}",
            file=sys.stderr,
        )
        return None


def promote(module: str, stage: str, run_n: int) -> None:
    """Atomic per-entry merge promote.

    1. Build new canonical view in .promote-tmp/ (all hardlinks)
    2. Per-entry merge: for each entry in .promote-tmp/, rmtree/unlink
       canonical's same-name target if exists, then os.rename into place
    3. Best-effort delete old canonical entries not in new view

    Step 1 failure (any hardlink/mkdir error) → .promote-tmp cleared,
    canonical fully intact. Step 2 partial failure may leave canonical in
    a partial state; repair_partial_promote_if_needed cleans leftover
    .promote-tmp/ on the next cmd entry.
    """
    stage_dir = _result_path(module, stage).parent
    run_dir = stage_dir / "runs" / str(run_n)
    rj_src = run_dir / "result.json"
    if not rj_src.exists():
        raise FileNotFoundError(f"run result.json missing: {rj_src}")
    artifacts = json.loads(rj_src.read_text()).get("artifacts", [])

    tmp = stage_dir / ".promote-tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    try:
        # Step 1: build new canonical view in .promote-tmp/
        os.link(str(rj_src), str(tmp / "result.json"))
        for art in artifacts:
            # result.json is already linked above; a producer that self-lists it
            # in artifacts[] would re-link into the same path → FileExistsError.
            # The envelope schema rejects self-listing, but keep the primitive safe.
            if art["path"] == "result.json":
                continue
            src = run_dir / art["path"]
            if not src.exists():
                raise FileNotFoundError(f"artifact missing: {src}")
            dst = tmp / art["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not src.is_symlink() and src.is_dir():
                _cp_al(src, dst)
            else:
                # Regular file OR symlink (to file or dir): hardlink at inode level.
                # For symlinks, follow_symlinks=False preserves the symlink as-is.
                os.link(
                    str(src),
                    str(dst),
                    follow_symlinks=False if src.is_symlink() else True,
                )

        # Step 2: per-entry merge — handle non-empty target dirs (POSIX rename
        # ENOTEMPTY guard). For each entry in .promote-tmp/, rmtree/unlink
        # canonical target if exists, then rename .promote-tmp/X to canonical/X.
        new_canonical_names = {entry.name for entry in tmp.iterdir()}
        for entry in list(tmp.iterdir()):
            target = stage_dir / entry.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            os.rename(str(entry), str(target))
        tmp.rmdir()

        # Step 3: best-effort delete old canonical entries not in new view
        for entry in list(stage_dir.iterdir()):
            if entry.name in ("runs", ".promote-tmp"):
                continue
            if entry.name in new_canonical_names:
                continue  # part of new view, keep
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError:
                pass  # best-effort

    except Exception:
        # Step 1 failure rolls back fully — canonical untouched
        if tmp.exists():
            shutil.rmtree(tmp)
        raise


def repair_partial_promote_if_needed(module: str, stage: str) -> None:
    """Per-cmd-entry fix-up for partial promote crashes.

    A crashed promote() may leave `.promote-tmp/` populated if the process
    was killed before the except-handler's rmtree could run (SIGKILL, OOM,
    OS panic). Detection signal: `.promote-tmp/` exists at start of any
    cmd. Action: rmtree it so the subsequent promote() retry can rebuild
    from scratch.

    Note: this DOES NOT restore canonical to a known-good state. Canonical
    may remain in a partial state (some entries from run N, some still
    from run N-1, some missing). The subsequent promote() retry in
    cmd_reap (called by orchestrator) will overwrite whatever partial
    state exists via the per-entry merge step.

    Idempotent: safe to call repeatedly with no .promote-tmp present.
    """
    stage_dir = _result_path(module, stage).parent
    tmp = stage_dir / ".promote-tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
