"""Module storage: event I/O, artifact validation, input protection and publication."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

sys.path.insert(0, str(Path(__file__).parent))
import rules  # noqa: E402

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_EVENT_SCHEMA_DIR = _PLUGIN_ROOT / "framework" / "references" / "schemas" / "events"


def module_root(module: str) -> Path:
    """Use the module directory path supplied by the caller."""
    return Path(module)


def events_path(module: str) -> Path:
    return module_root(module) / "events.jsonl"


def read_events(module: str) -> list[dict]:
    p = events_path(module)
    if not p.exists():
        return []
    out = []
    for i, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            sys.exit(f"read_events: corrupt line {i} of {p}: {e.msg}")
    return out


def _event_schema(etype: str) -> dict:
    path = _EVENT_SCHEMA_DIR / f"{etype}.schema.json"
    if not path.exists():
        sys.exit(f"append_event: no schema for event type {etype!r}")
    return json.loads(path.read_text())


_ENVELOPE_URI = "https://veripower.local/schemas/envelope.schema.json"
_ENVELOPE_SCHEMA_PATH = (
    _PLUGIN_ROOT / "framework" / "references" / "schemas" / "envelope.schema.json"
)


def _envelope_registry() -> Registry:
    """Register the shared envelope for event and stage schema references."""
    envelope = Resource.from_contents(
        json.loads(_ENVELOPE_SCHEMA_PATH.read_text()),
        default_specification=DRAFT202012,
    )
    return Registry().with_resource(_ENVELOPE_URI, envelope)


def freeze_inputs(module: str) -> None:
    """Remove owner-write permission from the intent tree at each CLI invocation.

    Preserve other permission bits and leave symlink targets unchanged."""
    for key in rules.PIPELINE_INPUTS:
        root = module_root(module) / key
        if not root.exists():
            continue
        for q in (root, *root.rglob("*")):
            if (
                q.is_symlink()
            ):  # chmod follows a link; its target may be outside the tree
                continue
            q.chmod(q.stat().st_mode & ~0o200)


def append_event(module: str, event: dict, ts: str) -> None:
    etype = event.get("type")
    record = {"ts": ts, **event}  # ts first
    try:
        jsonschema.Draft202012Validator(
            _event_schema(etype), registry=_envelope_registry()
        ).validate(record)
    except jsonschema.ValidationError as e:
        sys.exit(f"append_event: {etype} schema violation: {e.message}")
    read_events(module)
    p = events_path(module)
    p.parent.mkdir(parents=True, exist_ok=True)
    previous = p.read_bytes() if p.exists() else b""
    separator = b"\n" if previous and not previous.endswith(b"\n") else b""
    record_bytes = json.dumps(record, ensure_ascii=False).encode() + b"\n"
    payload = separator + record_bytes
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666)
    try:
        if os.write(fd, payload) != len(payload):
            raise OSError(f"append_event: incomplete write to {p}")
    finally:
        os.close(fd)


def _stage_result_schema_path(rule_name: str) -> Path:
    """The rule's own result.schema.json, resolved from its skill name
    (`veripower:<dir>` -> skills/<dir>/references/result.schema.json)."""
    skill_dir = rules.RULES[rule_name].skill.split(":", 1)[1]
    return _PLUGIN_ROOT / "skills" / skill_dir / "references" / "result.schema.json"


def validate_result(rule_name: str, result: dict) -> str | None:
    """Return the first stage-schema error, or None for a valid result.

    Schema-loading errors are reported as validation errors."""
    try:
        stage_schema = json.loads(_stage_result_schema_path(rule_name).read_text())
        validator = jsonschema.Draft202012Validator(
            stage_schema, registry=_envelope_registry()
        )
        errors = sorted(
            validator.iter_errors(result), key=lambda e: list(e.absolute_path)
        )
    except Exception as e:
        return f"schema validation internal error: {type(e).__name__}: {e}"
    if not errors:
        return None
    err = errors[0]
    path = "$" + "".join(
        f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path
    )
    return f"schema violation at {path}: {err.message}"


def _result_path(root: Path, rule: str) -> Path:
    return Path(root, *rules.workdir_root(rule), "result.json")


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
    root: Path,
    rule: str,
    workdir,
    params=None,
    scope=None,
    caused_by=None,
    reasons=None,
) -> None:
    """Write absolute input locations and supplied rework context to dispatch.json.

    Stage inputs name their producer's canonical directory; external inputs name
    their own root. The sim_run parameter selects a historical simulation run.
    Scope, source records and decision reasons are supplied by the kernel."""
    r = rules.RULES[rule]
    table: dict[str, str] = {}
    for key, globs in r.inputs.items():
        g0 = globs[0]
        if g0 in rules.PIPELINE_INPUTS:
            table[key] = str((root / g0).resolve())
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
    "dispatch.json",
)


def carry_self(root: Path, rule: str, workdir) -> None:
    """Copy the rule's selected canonical products into a fresh run directory.

    Use writable copies so edits leave the source run unchanged. Exclude framework
    files and the rule's per-round review records."""
    r = rules.RULES[rule]
    if not r.carry:
        return
    stage_dir = _result_path(root, rule).parent
    if not stage_dir.is_dir():
        return
    dest = Path(workdir)
    products = (
        p
        for p in stage_dir.iterdir()
        if p.name not in _CARRY_EXCLUDE and not p.is_symlink()
    )
    sources = (src for p in products for src in (p.rglob("*") if p.is_dir() else [p]))
    for src in sources:
        if not src.is_file() or src.is_symlink():
            continue
        rel = src.relative_to(stage_dir)
        rel_str = rel.as_posix()
        if not any(fnmatch.fnmatch(rel_str, g) for g in r.carry):
            continue
        if any(fnmatch.fnmatch(rel_str, ng) for ng in r.no_carry):
            continue
        d = dest / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, d)
        os.chmod(d, d.stat().st_mode | 0o200)


def _cp_al(src: Path, dst: Path) -> None:
    """Hardlink a directory tree, preserving symlink inodes without following them."""
    if dst.exists():
        raise FileExistsError(f"_cp_al dst exists: {dst}")
    dst.mkdir()
    for entry in src.iterdir():
        if entry.is_symlink():
            # Preserve the symlink inode without traversing its target.
            os.link(str(entry), str(dst / entry.name), follow_symlinks=False)
        elif entry.is_dir():
            _cp_al(entry, dst / entry.name)
        else:
            os.link(str(entry), str(dst / entry.name))


def _artifact_roots(artifacts: list[dict]) -> list[Path]:
    """Select each declared file once, including files covered by a directory."""
    roots: list[Path] = []
    for rel in sorted(
        {Path(a["path"]) for a in artifacts}, key=lambda p: (len(p.parts), str(p))
    ):
        if rel == Path("result.json"):
            continue
        if not _is_safe_rel(str(rel)):
            raise ValueError(f"artifact path escapes run dir: {rel}")
        if not rel.parts or rel.parts[0] == "runs":
            raise ValueError(f"artifact path conflicts with run storage: {rel}")
        if not any(parent in rel.parents for parent in roots):
            roots.append(rel)
    return roots


def promote(root: Path, rule: str, run_n: int) -> None:
    """Publish a prepared view; restore the previous view if a move fails.

    Run directories retain the source artifacts. Interrupted process termination
    can leave a staging directory; an explicit reap rebuilds the requested view.
    """
    stage_dir = _result_path(root, rule).parent.resolve()
    run_dir = stage_dir / "runs" / str(run_n)
    rj_src = run_dir / "result.json"
    artifacts = _artifact_roots(json.loads(rj_src.read_text()).get("artifacts", []))
    temporary = Path(tempfile.mkdtemp(prefix=".promote-", dir=stage_dir))
    ready, previous = temporary / "ready", temporary / "previous"
    moved, published = [], []
    try:
        ready.mkdir()
        previous.mkdir()
        os.link(rj_src, ready / "result.json")
        for rel in artifacts:
            src, dst = run_dir / rel, ready / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not src.is_symlink() and src.is_dir():
                _cp_al(src, dst)
            else:
                os.link(src, dst, follow_symlinks=False)

        for entry in list(stage_dir.iterdir()):
            if entry.name == "runs" or entry == temporary:
                continue
            os.rename(entry, previous / entry.name)
            moved.append(entry.name)
        for entry in list(ready.iterdir()):
            os.rename(entry, stage_dir / entry.name)
            published.append(entry.name)
    except BaseException:
        for name in reversed(published):
            os.rename(stage_dir / name, ready / name)
        for name in reversed(moved):
            os.rename(previous / name, stage_dir / name)
        shutil.rmtree(temporary)
        raise
    shutil.rmtree(temporary)
