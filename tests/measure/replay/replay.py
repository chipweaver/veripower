#!/usr/bin/env python3
"""Replay a REAL veripower event log against a scheduler and compare, decision by decision.

The log is what CoreMiniAxi run06 actually produced (2026-07-29 .. 08-02, 75 events; the only
round in the Coral-NPU eval repo that reached `signoff`). At every point where the real
Orchestrator must have called `decide`, this asks a scheduler what it would do from the state
that existed at that moment, and puts the answer next to what really happened.

WHY THE BYTES ARE SURROGATE, AND WHY THAT IS NOT A STUB
------------------------------------------------------
`decide` consumes exactly two things from disk: whether a path exists, and whether a file's
fingerprint equals one recorded in the log. It never reads content. So relabelling every
fingerprint through a bijection and writing bytes that hash to the new labels preserves every
question the scheduler can ask. What is reconstructed is the *equality structure* of the tree
at each moment — which is the whole of the tree the scheduler sees. Labels are not computed by
re-deriving facts.fingerprint's formula: every surrogate object is materialised once in a probe
tree and its label READ BACK through facts.fingerprint, so a dir's `merkle:` label cannot drift
from the real one.

Two paths are exceptions, and both are handled rather than surrogated:
  * `<workdir_root>/result.json` — `schedule._declared_owner` DOES read this one, for
    `stage_specific.fix_owner`. Its surrogate is a real envelope carrying the real verdict and
    the real fix_owner (FIX_OWNER below), with the source fingerprint embedded so the bijection
    still holds.
  * a per-run `runs/<n>/result.json` — `_ready_to_reap` scans for its existence. Materialised
    for an in-flight run iff the log's next event is that run's outcome, i.e. iff the executor
    had in fact finished when the real Orchestrator looked.

REGISTRY DRIFT, AND WHAT IS SYNTHESISED BECAUSE OF IT
-----------------------------------------------------
The run predates today's registry by about a week: `clocks.json`, `features.json`,
`check-hints/*.json`, `top-io.json`, `interconnects.json`, the per-child review dirs,
`tb-scaffold.json`, `sequences.json`, `power-scenarios.json`, `local.sgdc`,
`constraints.local.sdc`, `conformance-review.md` and `reports_ptpx/*/power_hier.rpt` are
declared today and were never produced then. Without them every downstream rule is
`input_available=False` and the replay degenerates to ESCALATE everywhere — a fixture artefact,
not a finding. Each such selector gets ONE synthetic file per producing run, stamped with the
run number so it drifts across rounds exactly as a real output would, and injected into the
recorded inputs of every consumer whose selector matches it — so a consumer's proof goes stale
when the producer re-runs, which is the property the scheduler actually reads.

WHAT IS RECONSTRUCTED RATHER THAN READ
--------------------------------------
FIX_OWNER. All four surviving simulation failure envelopes in the live tree carry
fix_owner=None — this run used the triage channel 5/5 times. power-analysis run 1's envelope
did not survive; the real routing (`pa:1 fail` -> `dispatch simulation:7`) plus TRACE-ISSUES.md
PLG-13 fix it as `simulation`. That one value is an inference.

NOT COVERED: the closing/signoff decision. A pin's `content_fingerprint` is taken over an
oracle *selector*, not one recorded path, so the bijection does not carry it.

The log itself is NOT in the repo — it is one run's record, not a plugin artifact. Pass it
with --log; `README.md` says which run the numbers there were taken from.

    python3 replay.py --scripts <dir containing schedule.py> --tag v4 --log <events.jsonl>
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
# Intermediate trees are regenerable and large-ish; keep them out of the repo.
SCRATCH = (
    Path(os.environ.get("VP_SCRATCH", tempfile.gettempdir())) / "vp-real-log-replay"
)
PROBE = SCRATCH / "probe"

# Reconstructed attributions — see module docstring. rule -> {run: fix_owner}
FIX_OWNER: dict[str, dict[int, str | None]] = {
    "simulation": {1: None, 2: None, 3: None, 4: None, 5: None},
    "power-analysis": {1: "simulation"},  # inferred
}


def load(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def seg_match(path: str, pat: str) -> bool:
    """Path.glob semantics: `*` does not cross a separator."""
    ps, qs = path.split("/"), pat.split("/")
    return len(ps) == len(qs) and all(fnmatch.fnmatch(a, b) for a, b in zip(ps, qs))


# ── registry drift: synthesise the outputs today's rules declare and this run lacks ──


def missing_selectors(rules, rule_name, produced):
    """Declared output selectors THIS run failed to match, as one concrete path each.

    Per-run, not per-rule: the plugin changed under this run (rtl-design:1 emitted
    `rtl-files.json` + `constraint-annotations.json`; runs 2-4 emitted `filelist.txt`
    instead), so a union over the whole log would hide a gap that really was there at
    the moment the scheduler looked.

    A selector under a recorded DIRECTORY needs no filler and must not get one: the
    directory materialises with a child, so the glob already resolves — and adding a
    second child would change the directory's merkle away from its recorded label,
    silently failing proof_valid's output condition for every prefix after it."""
    root = "/".join(rules.workdir_root(rule_name))
    dirs = [p.split("/") for p, v in produced.items() if v.startswith("merkle:")]
    out = []
    for sel in rules.RULES[rule_name].outputs:
        full = f"{root}/{sel}"
        segs = full.split("/")
        if any(seg_match(p, full) for p in produced):
            continue
        if any(len(d) < len(segs) and segs[: len(d)] == d for d in dirs):
            continue  # a recorded directory already covers it
        out.append(full.replace("*", "synth"))
    return out


def augment(events, rules):
    """Add the synthetic outputs to each producing run, and thread their values through every
    consumer's recorded inputs so staleness propagates the way it would have."""
    fillers: dict[str, set] = {}
    live: dict[str, str] = {}  # synthetic path -> value as of the walk position
    for e in events:
        if e["type"] != "outcome":
            continue
        rule, run = e["rule"], e["run"]
        # 1. this run consumed whatever the producers had last written
        consumed = {}
        for globs in rules.RULES[rule].inputs.values():
            for g in globs:
                for p, v in live.items():
                    if seg_match(p, g):
                        consumed[p] = v
        for proof in e.get("proofs") or []:
            proof.setdefault("inputs", {}).update(consumed)
        # 2. and then produced its own, stamped with the run so a re-run drifts them
        if e["verdict"] != "blocked":
            for p in missing_selectors(rules, rule, dict(e.get("outputs") or {})):
                v = "sha256:" + hashlib.sha256(f"{rule}:{run}:{p}".encode()).hexdigest()
                e.setdefault("outputs", {})[p] = v
                live[p] = v
                fillers.setdefault(rule, set()).add(p)
    return events, fillers


# ── surrogate objects: labels read back through facts.fingerprint, never re-derived ──


class Surrogate:
    def __init__(self, events, facts):
        self.facts = facts
        self.body: dict[
            str, str
        ] = {}  # real fp -> file bytes (None => it is a directory)
        self.isdir: dict[str, bool] = {}
        self.new: dict[str, str] = {}  # real fp -> surrogate fp
        envelope: dict[str, tuple[str, str, int]] = {}
        for e in events:
            if e["type"] != "outcome":
                continue
            for path, fp in (e.get("outputs") or {}).items():
                if Path(path).name == "result.json":
                    envelope.setdefault(fp, (e["verdict"], e["rule"], e["run"]))
        self._envelope = envelope

        for fp in self._all_fps(events):
            hit = envelope.get(fp)
            if hit:
                verdict, rule, run = hit
                env = {
                    "schema_version": "1.0",
                    "status": verdict,
                    "stage_specific": {"_replay_source_fingerprint": fp},
                }
                owner = FIX_OWNER.get(rule, {}).get(run)
                if owner:
                    env["stage_specific"]["fix_owner"] = owner
                self.body[fp] = json.dumps(env, indent=2, sort_keys=True)
            else:
                self.body[fp] = fp + "\n"
            self.isdir[fp] = fp.startswith("merkle:")
        self._label()

    @staticmethod
    def _all_fps(obj, acc=None):
        acc = set() if acc is None else acc
        if isinstance(obj, str):
            if obj.startswith(("sha256:", "merkle:")):
                acc.add(obj)
        elif isinstance(obj, list):
            for x in obj:
                Surrogate._all_fps(x, acc)
        elif isinstance(obj, dict):
            for v in obj.values():
                Surrogate._all_fps(v, acc)
        return acc

    def _label(self):
        """Materialise every distinct object once, read its label back through the real
        fingerprint function. No formula is duplicated here."""
        if PROBE.exists():
            shutil.rmtree(PROBE)
        PROBE.mkdir(parents=True)
        for i, (fp, body) in enumerate(sorted(self.body.items())):
            p = PROBE / f"o{i:05d}"
            if self.isdir[fp]:
                p.mkdir()
                (p / "_content").write_text(body)
            else:
                p.write_text(body)
            self.new[fp] = self.facts.fingerprint(p)
        assert len(set(self.new.values())) == len(self.new), "surrogate labels collided"

    def write(self, dest: Path, fp: str):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.isdir[fp]:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "_content").write_text(self.body[fp])
        else:
            dest.write_text(self.body[fp])

    def relabel(self, obj):
        if isinstance(obj, str):
            return (
                self.new.get(obj, obj)
                if obj.startswith(("sha256:", "merkle:"))
                else obj
            )
        if isinstance(obj, list):
            return [self.relabel(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.relabel(v) for k, v in obj.items()}
        return obj


# ── the tree as it stood ──────────────────────────────────────────────────────────


def canonical_state(prefix):
    """{path: fp} after `prefix`. store.promote replaces a stage's canonical view wholesale
    with the reaped run's product set, and the outcome's `outputs` IS that post-promote set —
    so a stage's files are exactly its latest non-blocked outcome's outputs, not a union."""
    by_stage: dict[str, dict] = {}
    for e in prefix:
        if e["type"] == "outcome" and e["verdict"] != "blocked":
            by_stage[e["rule"]] = e.get("outputs") or {}
    disk = {}
    for outs in by_stage.values():
        disk.update(outs)
    return disk


def materialize(tree: Path, prefix, sur: Surrogate, brainstorm_fp, ready):
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True)
    if brainstorm_fp:
        sur.write(tree / "brainstorm.md", brainstorm_fp)
    for path, fp in canonical_state(prefix).items():
        sur.write(tree / path, fp)
    if ready:
        p = tree / ready / "result.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"schema_version": "1.0", "status": "pass"}, indent=2))
    with (tree / "events.jsonl").open("w") as fh:
        for e in prefix:
            fh.write(json.dumps(sur.relabel(e), ensure_ascii=False) + "\n")


def fmt(a):
    act = a["action"]
    if act == "DISPATCH":
        cb = ",".join(f"{r}:{n}" for r, n in a.get("caused_by", []))
        refs = ",".join(a.get("diagnosis_refs", []))
        s = f"DISPATCH {a['rule']}"
        if cb:
            s += f" caused_by=[{cb}]"
        if refs:
            s += f" diag=[{refs}]"
        return s
    if act == "REAP":
        return f"REAP {a['rule']}:{a['run']}"
    if act == "YIELD":
        return "YIELD " + ",".join(f"{f['rule']}:{f['run']}" for f in a["in_flight"])
    if act == "ESCALATE":
        return "ESCALATE " + a.get("reason", "")
    return act


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--log", required=True, help="a real run's events.jsonl (README)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(args.scripts).resolve()))
    import facts  # noqa: E402
    import rules  # noqa: E402
    import schedule  # noqa: E402

    events = load(Path(args.log))
    events, fillers = augment(events, rules)
    sur = Surrogate(events, facts)

    bfp = None
    for e in events:
        for src in [e.get("inputs") or {}] + [
            p.get("inputs") or {} for p in (e.get("proofs") or [])
        ]:
            if "brainstorm.md" in src:
                bfp = src["brainstorm.md"]
        if bfp:
            break

    tree = SCRATCH / f"tree-{args.tag}" / "m"
    rows = []
    for k, e in enumerate(events):
        if e["type"] not in ("dispatch", "outcome"):
            continue
        prefix = events[:k]
        ready = None
        if e["type"] == "outcome":
            ready = next(
                (
                    d.get("workdir")
                    for d in prefix
                    if d["type"] == "dispatch"
                    and d["rule"] == e["rule"]
                    and d["run"] == e["run"]
                ),
                None,
            )
        materialize(tree, prefix, sur, bfp, ready)
        try:
            a = schedule.decide(str(tree))
        except Exception as exc:
            a = {"action": "CRASH", "reason": f"{type(exc).__name__}: {exc}"}
        want = (
            f"DISPATCH {e['rule']}:{e['run']}"
            if e["type"] == "dispatch"
            else f"REAP {e['rule']}:{e['run']}"
        )
        got = fmt(a)
        same = (a["action"] == "DISPATCH" and a["rule"] == e["rule"]) or (
            a["action"] == "REAP" and (a["rule"], a["run"]) == (e["rule"], e["run"])
        )
        rows.append(
            {
                "k": k,
                "ts": e.get("ts", "")[:19],
                "real": want,
                "decide": got,
                "action": a["action"],
                "agree": same,
                "raw": a,
            }
        )

    out = OUT / f"replay-{args.tag}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = sum(r["agree"] for r in rows)
    print(
        f"[{args.tag}] {n}/{len(rows)} decision points agree with the real run -> {out}"
    )
    print(
        f"        synthesised selectors: {sum(len(v) for v in fillers.values())} "
        f"across {len(fillers)} rules"
    )
    for r in rows:
        if not r["agree"] or args.verbose:
            mark = " " if r["agree"] else "!"
            print(
                f" {mark} k={r['k']:3d} {r['ts']}  real={r['real']:30s} decide={r['decide']}"
            )


if __name__ == "__main__":
    main()
