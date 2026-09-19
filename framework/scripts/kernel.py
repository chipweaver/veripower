"""Kernel CLI: validate commands, derive outcomes and coordinate storage updates."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import facts  # noqa: E402
import rules  # noqa: E402
import schedule  # noqa: E402
import store  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _resolve_inputs(module: str, rule_name: str) -> dict:
    """Version table of every input selector match (module-relative path -> fingerprint).
    Sole source of proof.inputs for proof-producing rules."""
    rule = rules.RULES[rule_name]
    root = store.module_root(module)
    table: dict[str, str] = {}
    for globs in rule.inputs.values():
        for g in globs:
            for p in sorted(root.glob(g)):
                rel = str(p.relative_to(root))
                table[rel] = facts.fingerprint(p)
    return table


def _run_envelope(rule_name, run) -> str:
    return str(Path(*rules.workdir_root(rule_name), "runs", str(run), "result.json"))


def _diagnosis_sources(events, diag) -> list[str]:
    """Return the failed run's result and, for triage, the analysis that authored the diagnosis."""
    subject = diag["subject"]
    out = []
    analyst = rules.RULES[subject["proof"]].triage
    if diag["source"] == "triage" and analyst:
        here = next(
            (
                i
                for i, e in enumerate(events)
                if e["type"] == "diagnosis" and e["id"] == diag["id"]
            ),
            len(events),
        )
        run = next(
            (
                e["run"]
                for e in reversed(events[:here])
                if e["type"] == "dispatch"
                and e["rule"] == analyst
                and e.get("params", {}).get("sim_run") == subject["outcome_run"]
            ),
            None,
        )
        if run is not None:
            out.append(_run_envelope(analyst, run))
    out.append(_run_envelope(subject["proof"], subject["outcome_run"]))
    return out


def cmd_dispatch(
    module,
    rule,
    diagnosis_refs,
    extra_params=None,
    caused_by=None,
):
    """Check input availability and in-flight work, then create and record a run.

    Resolve diagnosis references and causal results before creating the workdir.
    Parameters identify diagnostic inputs; caused_by and diagnosis_refs identify
    the failures and attributions this run addresses."""
    if extra_params is not None and not isinstance(extra_params, dict):
        return {"ok": False, "error": "--params must be a JSON object"}
    events = store.read_events(module)
    if any(f["rule"] == rule for f in facts.in_flight(events)):
        return {"ok": False, "error": f"{rule} already in-flight"}
    if not facts.rule_available(module, events, rule):
        return {"ok": False, "error": f"{rule} inputs not available"}
    # Check diagnostic parameters before creating a workdir.
    missing = [
        p for p in rules.RULES[rule].params if not (extra_params and p in extra_params)
    ]
    if missing:
        return {
            "ok": False,
            "error": f"{rule} dispatch missing required --params {missing} "
            f"(Rule.params={list(rules.RULES[rule].params)})",
        }
    root = store.module_root(module)
    # Resolve the two rework channels BEFORE allocating a run: an unresolvable one is a
    # caller error, and failing here leaves no half-created workdir behind.
    caused_by_paths = []
    for cb_rule, cb_run in caused_by or []:
        rel = Path(*rules.workdir_root(cb_rule), "runs", str(cb_run), "result.json")
        if not (root / rel).is_file():
            return {
                "ok": False,
                "error": f"--caused-by {cb_rule}:{cb_run} has no result.json",
            }
        caused_by_paths.append(str(rel))
    # Resolve the records and decision reasoning named by each diagnosis.
    by_id = {e["id"]: e for e in events if e["type"] == "diagnosis"}
    scope = facts.stale_inputs(module, events, rule)
    reasons = []
    for ref in diagnosis_refs or []:
        diag = by_id.get(ref)
        if diag is None:
            return {"ok": False, "error": f"unknown diagnosis ref {ref!r}"}
        for rel in _diagnosis_sources(events, diag):
            if rel not in caused_by_paths and (root / rel).is_file():
                caused_by_paths.append(rel)
        if diag.get("reason"):
            reasons.append(diag["reason"])
    run = facts.runs_of(events, rule) + 1
    workdir = str(Path(*rules.workdir_root(rule), "runs", str(run)))
    (root / workdir).mkdir(parents=True, exist_ok=True)
    abs_workdir = root / workdir
    store.carry_self(root, rule, abs_workdir)  # self-carry (no-op unless Rule.carry)
    store.write_dispatch(
        root, rule, abs_workdir, extra_params, scope, caused_by_paths, reasons
    )
    ev = {
        "type": "dispatch",
        "rule": rule,
        "run": run,
        "workdir": workdir,
        "params": dict(extra_params) if extra_params else {},
    }
    if caused_by:
        ev["caused_by"] = [[r, n] for r, n in caused_by]
    if rules.RULES[
        rule
    ].proof:  # only proof-producing rules record the input version table
        ev["inputs"] = _resolve_inputs(module, rule)
    if diagnosis_refs:
        ev["diagnosis_refs"] = diagnosis_refs
    store.append_event(module, ev, _now())
    return {
        "ok": True,
        "rule": rule,
        "run": run,
        # CLI paths are absolute; stored event paths remain module-relative.
        "workdir": str(abs_workdir.resolve()),
        "skill": rules.RULES[rule].skill,
        "execution": rules.RULES[rule].execution,
    }


def cmd_reap(module, rule, run):
    events = store.read_events(module)
    # Repeated reaps support interrupted publication.
    workdir = facts.run_workdir(events, rule, run)
    if workdir is None:
        return {"ok": False, "error": f"no dispatch event for {rule} run {run}"}
    root = store.module_root(module)
    rj = root / workdir / "result.json"
    # UNIFORM 4-tuple across proof rules AND triage — never a shape-shifting return.
    verdict, reason, proofs, diagnoses = _derive_verdict(rule, run, rj, events)
    if verdict != "blocked":  # promote produced artifacts (pass and fail both promote)
        try:
            store.promote(store.module_root(module), rule, run)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"promote failed: {e}"}
    outputs = _fingerprint_outputs(module, rule) if verdict != "blocked" else {}
    ev = {
        "type": "outcome",
        "rule": rule,
        "run": run,
        "verdict": verdict,
        "outputs": outputs,
        "proofs": proofs,
        "tool_versions": _tool_versions(),
    }
    if reason:
        ev["reason"] = reason
    if verdict != "blocked":
        # Record requirement verdicts for signoff review.
        judged = json.loads(rj.read_text())["stage_specific"].get("requirements")
        if judged:
            ev["requirements"] = judged
    store.append_event(module, ev, _now())
    for diagnosis in diagnoses:  # triage complete -> land the attributions
        store.append_event(module, diagnosis, _now())
    return {
        "ok": True,
        "rule": rule,
        "run": run,
        "verdict": verdict,
        **({"reason": reason} if reason else {}),
    }


def _fingerprint_outputs(module, rule):
    """Fingerprint the published result.json and every artifact it declares."""
    root = store.module_root(module)
    cdir = Path(*rules.workdir_root(rule))
    table = {}
    rj_rel = cdir / "result.json"
    table[str(rj_rel)] = facts.fingerprint(root / rj_rel)
    arts = json.loads((root / rj_rel).read_text())["artifacts"]
    for a in arts:
        rel = cdir / a["path"]
        table[str(rel)] = facts.fingerprint(root / rel)
    return table


def _tool_versions():
    """Audit-only identity record (never enters validity/re-run decisions):
    tool/library env identities + the plugin's own version."""
    import os
    import subprocess

    ids = {k: os.environ[k] for k in ("LIB_DB", "LIB_V", "UVM_HOME") if k in os.environ}
    try:
        p = subprocess.run(
            [
                "git",
                "-C",
                str(Path(__file__).resolve().parents[2]),
                "describe",
                "--always",
                "--dirty",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Record plugin identity when git can resolve the installation.
        if p.returncode == 0 and p.stdout.strip():
            ids["plugin"] = p.stdout.strip()
    except OSError:
        pass  # best-effort: absence never blocks a reap
    return ids


def _stale_result_reason(produced_at, dispatch_ts) -> str | None:
    """Reject results authored before their run's dispatch.

    Compare at second precision to match stage timestamps; interpret naive
    timestamps as UTC and report unparseable result timestamps."""

    def parse(s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    try:
        produced = parse(produced_at)
    except (ValueError, TypeError, AttributeError):
        return "produced_at_unparseable"
    try:
        dispatched = parse(dispatch_ts)
    except (ValueError, TypeError, AttributeError):
        return None  # kernel-authored ts; a malformed one is not the run's fault
    if produced < dispatched.replace(microsecond=0):
        return "stale_result"
    return None


def _derive_verdict(rule_name, run, rj: Path, events):
    """Derive the verdict, failure reason, proofs and diagnoses from a stage result."""
    rule = rules.RULES[rule_name]
    if not rj.is_file():
        return "blocked", "missing", [], []
    try:
        env = json.loads(rj.read_text())
    except (ValueError, OSError):
        return "blocked", "unparseable", [], []
    error = store.validate_result(rule_name, env)
    if error is not None:
        return "blocked", error, [], []
    status = env["status"]
    # Compare against this run's own dispatch timestamp.
    dispatch = next(
        e
        for e in reversed(events)
        if e["type"] == "dispatch" and e["rule"] == rule_name and e["run"] == run
    )
    stale = _stale_result_reason(env.get("produced_at"), dispatch["ts"])
    if stale:
        return "blocked", stale, [], []
    if rule_name == "simulation-triage":
        return _derive_triage(env, dispatch)  # same 4-tuple
    if rule.proof is None:
        return status, None, [], []
    # The outcome's artifact fingerprints also identify its evidence.
    proof = {
        "name": rule.proof,
        "verdict": status,
        "inputs": dispatch.get("inputs", {}),
    }
    return status, None, [proof], []


def _derive_triage(env, dispatch):
    """Group triage findings by root cause and derive one diagnosis per group.

    The originating dispatch identifies the failed simulation run. A root cause
    in the failed stage or its input producers can be a repair owner; other attributions require
    clarification. Empty findings block completion."""
    import uuid

    ss = env.get("stage_specific", {})
    findings = ss.get("findings") or []
    if not findings:
        return "blocked", "no_attribution", [], []
    sim_hit = dispatch["params"].get("sim_run")
    # Group findings by root cause; their locations and reasoning remain in the analysis.
    causes = list(dict.fromkeys(f["root_cause"] for f in findings))
    out = []
    for cause in causes:
        diagnosis = {
            "type": "diagnosis",
            "id": f"diag-{uuid.uuid4().hex[:12]}",
            "subject": {"proof": "simulation", "outcome_run": sim_hit},
            "attribution": cause,
            "source": "triage",
        }
        if cause in rules.repair_owners("simulation"):
            diagnosis["fix_owner"] = cause
        out.append(diagnosis)
    # Completed triage records diagnoses rather than an independent failed proof.
    return "pass", None, [], out


def cmd_diagnose(
    module,
    diag_id,
    subject_proof,
    subject_run,
    attribution,
    fix_owner,
    provenance,
    reason,
    supersedes,
):
    """Record a diagnosis decision with a legal repair owner, provenance and reason."""
    if fix_owner and fix_owner not in rules.repair_owners(subject_proof):
        return {
            "ok": False,
            "error": f"fix_owner {fix_owner!r} is neither {subject_proof!r} nor an input producer",
        }
    if not provenance:
        return {
            "ok": False,
            "error": "diagnose requires --provenance (source=decision)",
        }
    if not reason or not reason.strip():
        return {"ok": False, "error": "diagnose requires --reason (source=decision)"}
    ev = {
        "type": "diagnosis",
        "id": diag_id,
        "subject": {"proof": subject_proof, "outcome_run": subject_run},
        "attribution": attribution,
        "source": "decision",
        "provenance": provenance,
        "reason": reason,
    }
    if fix_owner:
        ev["fix_owner"] = fix_owner
    if supersedes:
        ev["supersedes"] = supersedes
    store.append_event(module, ev, _now())
    return {"ok": True, "id": diag_id}


def cmd_signoff(module, provenance, reason):
    """Check signoff readiness and record the authorized acceptance with its basis."""
    events = store.read_events(module)
    reason_blocked = facts.signoff_gate(module, events)
    if reason_blocked is not None:
        return {"ok": False, "error": reason_blocked}
    # Capture the evidence being accepted before appending the decision.
    basis = facts.signoff_basis(events)
    ev = {"type": "signoff", "provenance": provenance, "reason": reason}
    store.append_event(module, ev, _now())
    return {
        "ok": True,
        "module": module,
        "provenance": provenance,
        "basis": basis,
    }


def cmd_status(module):
    events = store.read_events(module)
    return {
        "module": module,
        "stages": facts.projection(module, events),
        "signed_off": facts.signed_off(module, events),
    }


def cmd_consequences(module, paths):
    """For each queried path, the currently-VALID proofs that would flip to invalid if
    that path's content changed — recomputed from the recorded input/output version
    tables of each proof's latest outcome (the same tables facts.proof_valid compares
    against disk), without touching disk."""
    events = store.read_events(module)
    out: dict[str, list[str]] = {}
    for path in paths:
        affected = []
        for rule_name, r in rules.RULES.items():
            if not r.proof:
                continue
            hit = facts.proof_outcome(events, r.proof)
            if hit is None:
                continue
            _, outcome = hit
            proof = next(p for p in outcome["proofs"] if p["name"] == r.proof)
            touched = set(proof.get("inputs", {})) | set(outcome.get("outputs", {}))
            # A tree fingerprint covers every path below it.
            covered = any(path == t or path.startswith(t + "/") for t in touched)
            if covered and facts.proof_valid(module, events, r.proof):
                affected.append(r.proof)
        out[path] = affected
    return {"paths": out}


def main():
    p = argparse.ArgumentParser(prog="kernel.py")
    sub = p.add_subparsers(dest="verb", required=True)
    module_help = (
        "path to the module directory — the one holding intent/, events.jsonl, "
        "Design/ and Verification/. Relative paths resolve against the current directory, "
        "so an absolute path works from anywhere (e.g. --module ~/chips/mydesign, or "
        "--module . inside it)."
    )
    d = sub.add_parser("decide")
    d.add_argument("--module", required=True, help=module_help)
    d.add_argument(
        "--wake",
        default=None,
        metavar="RULE:RUN",
        help="reap a run whose executor has exited, including one that left no result.json",
    )
    d.add_argument(
        "--closing",
        action="store_true",
        help="check signoff readiness at completion and return its basis; "
        "unmet signoff requirements return ESCALATE",
    )
    di = sub.add_parser("dispatch")
    di.add_argument("--module", required=True, help=module_help)
    di.add_argument("--rule", required=True, choices=list(rules.RULES))
    di.add_argument(
        "--caused-by",
        action="append",
        default=None,
        metavar="RULE:RUN",
        help="a failure this dispatch answers, e.g. --caused-by synthesis:1; repeat once "
        "per failure so a multi-cause rework names them all",
    )
    di.add_argument(
        "--diagnosis-refs",
        default=None,
        help="comma-separated diagnosis ids this auto-rebuild rests on (audit)",
    )
    di.add_argument(
        "--params",
        default=None,
        help="JSON object merged into the dispatch event's params, e.g. "
        "--params '{\"sim_run\": 5}' (simulation-triage; rules.RULES[rule].params "
        "names what a rule expects)",
    )
    re_ = sub.add_parser("reap")
    re_.add_argument("--module", required=True, help=module_help)
    re_.add_argument("--rule", required=True, choices=list(rules.RULES))
    re_.add_argument("--run", required=True, type=int)
    dg = sub.add_parser("diagnose")
    dg.add_argument("--module", required=True, help=module_help)
    dg.add_argument("--id", required=True, dest="diag_id")
    dg.add_argument("--subject-proof", required=True, choices=rules.FORWARD_PRIORITY)
    dg.add_argument("--subject-run", required=True, type=int)
    dg.add_argument("--attribution", required=True)
    dg.add_argument("--fix-owner", default=None, choices=rules.FORWARD_PRIORITY)
    dg.add_argument("--provenance", required=True)
    dg.add_argument("--reason", required=True)
    dg.add_argument("--supersedes", default=None)
    so = sub.add_parser("signoff")
    so.add_argument("--module", required=True, help=module_help)
    so.add_argument("--provenance", required=True)
    so.add_argument("--reason", required=True)
    st = sub.add_parser("status")
    st.add_argument("--module", required=True, help=module_help)
    co = sub.add_parser("consequences")
    co.add_argument("--module", required=True, help=module_help)
    co.add_argument("--paths", nargs="+", required=True)
    args = p.parse_args()
    # Reject nonexistent module directories before querying or mutating them.
    root = store.module_root(args.module)
    if not root.is_dir():
        sys.exit(f"kernel.py {args.verb}: no module directory at {root.resolve()}")
    refs = (
        args.diagnosis_refs.split(",")
        if getattr(args, "diagnosis_refs", None)
        else None
    )
    caused_by = []
    for spec in getattr(args, "caused_by", None) or []:
        cb_rule, _, cb_run = spec.partition(":")
        if cb_rule not in rules.RULES or not cb_run.isdigit() or int(cb_run) < 1:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"--caused-by {spec!r} is not <rule>:<run> with a known "
                        f"rule and a positive run",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        caused_by.append((cb_rule, int(cb_run)))
    extra_params = None
    if getattr(args, "params", None):
        try:
            extra_params = json.loads(args.params)
        except json.JSONDecodeError as e:
            print(
                json.dumps(
                    {"ok": False, "error": f"--params JSON parse error: {e}"},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
    handlers = {
        "decide": lambda: schedule.decide(
            args.module,
            wake=args.wake,
            closing=args.closing,
        ),
        "dispatch": lambda: cmd_dispatch(
            args.module,
            args.rule,
            refs,
            extra_params,
            caused_by,
        ),
        "reap": lambda: cmd_reap(args.module, args.rule, args.run),
        "diagnose": lambda: cmd_diagnose(
            args.module,
            args.diag_id,
            args.subject_proof,
            args.subject_run,
            args.attribution,
            args.fix_owner,
            args.provenance,
            args.reason,
            args.supersedes,
        ),
        "signoff": lambda: cmd_signoff(args.module, args.provenance, args.reason),
        "status": lambda: cmd_status(args.module),
        "consequences": lambda: cmd_consequences(args.module, args.paths),
    }
    store.freeze_inputs(args.module)
    print(json.dumps(handlers[args.verb](), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
