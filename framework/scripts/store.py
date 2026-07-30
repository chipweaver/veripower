"""VeriPower filesystem artifact-lifecycle helpers.

Split out so the kernel stays focused on state mutations. No I/O beyond the
promote operation itself. Imports only stdlib + rules (no
jsonschema/referencing deps).

Imported by kernel.py: its reap path calls `store.promote`.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rules  # noqa: E402


def _result_path(module: str, rule: str) -> Path:
    return Path("asic", module, *rules.workdir_root(rule), "result.json")


def _is_safe_rel(rel: str) -> bool:
    """True iff `rel` is a containment-safe relative path: not absolute and not
    escaping its base after normalization. Lexical only — does NOT resolve()
    (so a legitimate symlink artifact is unaffected; symlink-traversal is handled
    separately by _cp_al's follow_symlinks=False)."""
    if os.path.isabs(rel):
        return False
    norm = os.path.normpath(rel)
    return not (norm == ".." or norm.startswith(".." + os.sep))


def _resolve_sim_run(root: Path, sim_run) -> str:
    """Absolute location of a specific past simulation run: <sim-stage>/runs/<N>.
    Dedicated runtime guard (NOT _is_safe_rel, which rejects absolute paths): N must
    be a positive integer and the resolved runs/<N> must sit directly under the
    simulation stage's runs/ directory."""
    try:
        n = int(str(sim_run))
    except (TypeError, ValueError):
        raise ValueError(f"sim_run not an integer: {sim_run!r}")
    if n < 1:
        raise ValueError(f"sim_run must be a positive integer: {n}")
    sim_root = (root / Path(*rules.workdir_root("simulation"))).resolve()
    runs = sim_root / "runs"
    run_dir = (runs / str(n)).resolve()
    if run_dir.parent != runs:
        raise ValueError(f"sim_run escapes simulation runs/: {run_dir}")
    return str(run_dir)


def write_dispatch(
    module: str,
    rule: str,
    workdir,
    params=None,
    scope=None,
    caused_by=None,
    reasons=None,
) -> None:
    """dispatch-time dual of promote: write <workdir>/dispatch.json, the one thing the
    kernel tells a run about itself. Four keys, and a key is written only when it carries
    something:

    - `inputs` = {key: producer-canonical-stage-root (absolute)} — always present. Each
      key resolves to exactly one producer's canonical stage root; the consumer keeps the
      producer-output subpath literal (out/, tb/uvm/, constraints/). PIPELINE_INPUTS
      (external, no producer) resolve to the module root. A rule declaring 'sim_run' gets
      an extra 'sim_run' key = <simulation-stage>/runs/<N> (triage).
    - `scope` — module-relative paths, or <file>:<line> anchors, that narrow this round.
    - `caused_by` — module-relative per-run result.json of each failure this round answers.
    - `reasons` — verbatim human diagnosis reasoning.

    The three narrowing keys are derived by the caller (cmd_dispatch); this function owns
    only the file's shape."""
    r = rules.RULES[rule]
    root = Path("asic", module)
    module_root_abs = str(root.resolve())
    table: dict[str, str] = {}
    for key, globs in r.inputs.items():
        g0 = globs[0]
        if g0 in rules.PIPELINE_INPUTS:
            table[key] = module_root_abs
            continue
        # Every glob under one input key shares a single producer, so globs[0]'s
        # producer represents the whole key.
        prod = rules.producer_of(g0)
        if prod is None:
            raise ValueError(f"{rule}: input key {key!r} glob {g0!r} has no producer")
        table[key] = str((root / Path(*rules.workdir_root(prod))).resolve())
    if params and "sim_run" in r.params and "sim_run" in params:
        table["sim_run"] = _resolve_sim_run(root, params["sim_run"])
    doc: dict = {"inputs": table}
    if scope:
        doc["scope"] = list(scope)
    if caused_by:
        doc["caused_by"] = list(caused_by)
    if reasons:
        doc["reasons"] = list(reasons)
    (Path(workdir) / "dispatch.json").write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


_CARRY_EXCLUDE = (
    "result.json",
    "runs",
    ".promote-tmp",
    "dispatch.json",
)


def carry_self(module: str, rule: str, workdir) -> None:
    """dispatch-time: copy the author's own previous round into the fresh workdir so it
    edits incrementally. Source = the canonical stage root (the GC'd clean product set,
    parent of runs/), NOT runs/N-1. copy2 (NOT hardlink — canonical shares inodes with the
    producing run; a hardlink would let the author corrupt both), 0644 writable.

    Copies files whose stage-root-relative path matches a Rule.carry glob, minus Rule.no_carry
    (per-round review records), minus the framework-wide _CARRY_EXCLUDE top-level entries.
    No-op when Rule.carry is empty (pure transformers) or canonical does not exist (first run).
    Fresh empty workdir per dispatch → carry runs exactly once; session-resume does not re-dispatch."""
    r = rules.RULES[rule]
    if not r.carry:
        return
    stage_dir = _result_path(module, rule).parent
    if not stage_dir.is_dir():
        return
    dest = Path(workdir)
    for src in stage_dir.rglob("*"):
        if not src.is_file() or src.is_symlink():
            continue
        rel = src.relative_to(stage_dir)
        if rel.parts[0] in _CARRY_EXCLUDE:
            continue
        rel_str = rel.as_posix()
        if not any(fnmatch.fnmatch(rel_str, g) for g in r.carry):
            continue
        if any(fnmatch.fnmatch(rel_str, ng) for ng in r.no_carry):
            continue
        d = dest / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, d)
        os.chmod(d, 0o644)


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


def promote(module: str, rule: str, run_n: int) -> None:
    """Atomic per-entry merge promote.

    1. Build new canonical view in .promote-tmp/ (all hardlinks)
    2. Per-entry merge: for each entry in .promote-tmp/, rmtree/unlink
       canonical's same-name target if exists, then os.rename into place
    3. Best-effort delete old canonical entries not in new view

    Step 1 failure (any hardlink/mkdir error) → .promote-tmp cleared,
    canonical fully intact. Step 2 partial failure may leave canonical in
    a partial state; the next reap that promotes this stage re-runs
    promote(), which clears any stale .promote-tmp/ before starting and
    rebuilds from scratch — promote is idempotent.
    """
    stage_dir = _result_path(module, rule).parent
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
            # Same two-layer pattern as self-listing: the envelope schema rejects
            # `..`/absolute paths at validate_result, but keep the primitive safe
            # so a bypassed-validation producer can never hardlink outside runs/<N>/.
            if not _is_safe_rel(art["path"]):
                raise ValueError(f"artifact path escapes run dir: {art['path']}")
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
