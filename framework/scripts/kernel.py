"""VeriPower kernel CLI. The ONLY writer of events.jsonl. Verbs in §4.2."""

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
    Sole source of proof.inputs for proof-producing rules (§5.3)."""
    rule = rules.RULES[rule_name]
    root = facts.module_root(module)
    table: dict[str, str] = {}
    for globs in rule.inputs.values():
        for g in globs:
            for p in sorted(root.glob(g)):
                rel = str(p.relative_to(root))
                table[rel] = facts.fingerprint_cached(p, root)
    return table


def cmd_dispatch(
    module,
    rule,
    objective,
    conservative,
    directive_path,
    diagnosis_refs,
    extra_params=None,
):
    """Re-checks dispatchability AT THIS INSTANT (decide→dispatch drift guard, §4.2):
    in-flight premise, input availability, and — for frontend-signoff — the FULL signoff
    gate, so an explicit `dispatch --rule frontend-signoff` cannot bypass decide and mint
    a signoff proof (§3.6; §6 mandates the bypass-blocked test).

    extra_params (parsed --params JSON object, e.g. {"sim_run": 5} for simulation-triage
    per rules.RULES[rule].params) is merged into the recorded dispatch event's `params`
    BEFORE `directive`, so the two never collide (Task C7 — the generic complement to
    schedule.py's disposition, which already computes {"sim_run": <run>} for triage but
    had no CLI path to land it on the actual dispatch event)."""
    events = facts.read_events(module)
    if any(f["rule"] == rule for f in facts.in_flight(events)):
        return {"ok": False, "error": f"{rule} already in-flight"}
    if not facts.rule_available(module, events, rule):
        return {"ok": False, "error": f"{rule} inputs not available"}
    # Mandatory declared params must be supplied via --params (the `directive` channel is
    # optional and lands via --directive). Missing them mints a malformed event downstream:
    # a triage without sim_run derives a diagnosis with subject.outcome_run=None -> schema
    # violation AFTER the outcome already landed -> half-reap (F8a). Reject up front.
    required_params = [p for p in rules.RULES[rule].params if p != "directive"]
    missing = [p for p in required_params if not (extra_params and p in extra_params)]
    if missing:
        return {
            "ok": False,
            "error": f"{rule} dispatch missing required --params {missing} "
            f"(Rule.params={list(rules.RULES[rule].params)})",
        }
    if rule == "frontend-signoff":
        if objective != "signoff":
            return {
                "ok": False,
                "error": "frontend-signoff dispatches only under objective=signoff (§3.2)",
            }
        gate = schedule._signoff_gate(
            module, events
        )  # sys.exits '先开纪元' when no epoch
        if gate is not None:
            return {"ok": False, "error": gate["reason"]}
    run = facts.runs_of(events, rule) + 1
    workdir = str(Path(*rules.workdir_root(rule), "runs", str(run)))
    (facts.module_root(module) / workdir).mkdir(parents=True, exist_ok=True)
    params: dict = dict(extra_params) if extra_params else {}
    if directive_path:
        dst = facts.module_root(module) / workdir / "directive.md"
        # Byte-exact transfer (§3.4 禁 LLM 转写): read/write bytes, never text mode —
        # universal-newline translation (CRLF -> LF) would drift both the file and its
        # recorded digest from the source (e.g. a verbatim-forwarded triage result.json).
        data = (
            sys.stdin.buffer.read()
            if directive_path == "-"
            else Path(directive_path).read_bytes()
        )
        dst.write_bytes(data)
        params["directive"] = {
            "path": str(Path(workdir) / "directive.md"),
            "digest": facts.fingerprint(dst),
        }
    ev = {
        "type": "dispatch",
        "rule": rule,
        "run": run,
        "workdir": workdir,
        "params": params,
        "objective": objective,
    }
    if conservative:
        ev["conservative"] = True
    if rules.RULES[
        rule
    ].proof:  # only proof-producing rules record the input version table
        ev["inputs"] = _resolve_inputs(module, rule)
    if diagnosis_refs:
        ev["diagnosis_refs"] = diagnosis_refs
    facts.append_event(module, ev, _now())
    return {
        "ok": True,
        "rule": rule,
        "run": run,
        "workdir": workdir,
        "skill": rules.RULES[rule].skill,
        "execution": rules.RULES[rule].execution,
    }


def cmd_reap(module, rule, run, subagent_output_file=None):
    events = facts.read_events(module)
    # Guard BEFORE deriving anything: a dispatch event for (rule, run) must exist, or
    # there is no workdir to derive a verdict from (the prior bug: TypeError on
    # `root / None`). Re-reaping an ALREADY-outcome'd run is deliberately still
    # allowed — it is the documented crash-mid-promote repair path and the pin/regrade
    # mechanism (ARCHITECTURE.md §4.7/§7.2; test_pin_content_drift_regrades_...).
    workdir = schedule._workdir_of(events, rule, run)
    if workdir is None:
        return {"ok": False, "error": f"no dispatch event for {rule} run {run}"}
    root = facts.module_root(module)
    if subagent_output_file:
        store._mirror_subagent_trace(root / workdir, rule, subagent_output_file)
    rj = root / workdir / "result.json"
    # UNIFORM 4-tuple across proof rules AND triage — never a shape-shifting return.
    verdict, reason, proofs, diagnosis = _derive_verdict(module, rule, run, rj, events)
    if verdict != "blocked":  # promote produced artifacts (pass and fail both promote)
        try:
            store.promote(module, rule, run)
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
    facts.append_event(module, ev, _now())
    if diagnosis is not None:  # triage complete -> land the attribution (Task C7)
        facts.append_event(module, diagnosis, _now())
    return {"ok": True, "rule": rule, "run": run, "verdict": verdict}


def _fingerprint_outputs(module, rule):
    """Version table of the ACTUAL promote set (spec §2: 落账指纹按实际 promote 集记录,
    declared outputs are its lower bound): the canonical result.json itself plus every
    artifacts[] entry it lists — exactly what store.promote just merged into canonical."""
    root = facts.module_root(module)
    cdir = Path(*rules.workdir_root(rule))
    table = {}
    rj_rel = cdir / "result.json"
    table[str(rj_rel)] = facts.fingerprint_cached(root / rj_rel, root)
    try:
        arts = json.loads((root / rj_rel).read_text()).get("artifacts", [])
    except (OSError, ValueError):
        arts = []
    for a in arts:
        rel = cdir / a["path"]
        table[str(rel)] = facts.fingerprint_cached(root / rel, root)
    return table


def _tool_versions():
    """Audit-only identity record (§1.2 — never enters validity/re-run decisions):
    tool/library env identities + the plugin's own version."""
    import os
    import subprocess

    ids = {k: os.environ[k] for k in ("LIB_DB", "LIB_V", "UVM_HOME") if k in os.environ}
    try:
        ids["plugin"] = subprocess.run(
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
        ).stdout.strip()
    except OSError:
        pass  # best-effort: absence never blocks a reap
    return ids


def _oracle_content_fp(module, rule):
    """Current content fingerprint of a proposed oracle, per its Rule.oracle_selector
    (workdir-root-relative glob). Multiple matches merge deterministically (sorted)."""
    root = facts.module_root(module)
    base = root / Path(*rules.workdir_root(rule.name))
    paths = sorted(base.glob(rule.oracle_selector))
    if not paths:
        return facts.UNKNOWN
    if len(paths) == 1 and paths[0].is_file():
        return facts.fingerprint(paths[0])
    import hashlib

    h = hashlib.sha256()
    for p in paths:
        h.update(str(p.relative_to(base)).encode() + b"\0")
        h.update(facts.fingerprint(p).encode() + b"\0")
    return "merkle:" + h.hexdigest()


def _derive_verdict(module, rule_name, run, rj: Path, events):
    """UNIFORM return: (verdict, reason, proofs, diagnosis) — proofs is [] and diagnosis
    is None whenever not applicable; the shape NEVER varies by rule kind. result.json
    status -> verdict; missing/unparseable/malformed/schema-violation -> blocked. For
    simulation-triage (proof=None) the triage branch (Task C7) derives a diagnosis event
    dict from stage_specific — or blocked when it skipped/crashed."""
    rule = rules.RULES[rule_name]
    if not rj.is_file():
        return "blocked", "missing", [], None
    try:
        env = json.loads(rj.read_text())
    except (ValueError, OSError):
        return "blocked", "unparseable", [], None
    status = env.get("status")
    if status not in ("pass", "fail"):
        return "blocked", "malformed", [], None
    # schema validation reuses the per-stage result.schema.json via facts;
    # a schema violation -> ("blocked", "schema_violation", [], None).
    if facts.validate_result(rule_name, env) is not None:
        return "blocked", "schema_violation", [], None
    if rule_name == "simulation-triage":
        return _derive_triage(module, env, events, run)  # Task C7 — same 4-tuple
    if rule.proof is None:
        return status, None, [], None
    dispatch = next(
        e
        for e in reversed(events)
        if e["type"] == "dispatch" and e["rule"] == rule_name and e["run"] == run
    )
    cdir = Path(*rule.workdir_root)
    # evidence = canonical result.json AND its artifacts[] (§5.3 "及其 artifacts[]"): the
    # report-class products ARE the evidence; recording only result.json truncates the audit
    # trail. Audit-only — not in validity (all already covered by output binding, §5.3).
    evidence = [str(cdir / "result.json")] + [
        str(cdir / a["path"]) for a in env.get("artifacts", [])
    ]
    proof = {
        "name": rule.proof,
        "verdict": status,
        "inputs": dispatch.get("inputs", {}),
        "oracle": {"ref": rule.oracle[0], "grade": _graded(module, events, rule)},
        "evidence": evidence,
    }
    return status, None, [proof], None


def _derive_triage(module, env, events, run):
    """Triage reap (§2 triage contract): complete -> (verdict, None, [], diagnosis-event);
    skipped/crash -> blocked, no diagnosis (the sim failure stays ambiguous; next round
    re-dispatches triage, §3.3). Confidence lands as-is (P4) — reliability is decide's
    gate, not a reap branch. The root_cause map is route.TRIAGE_ROOT_CAUSE — route.py is
    the SINGLE home of failure→target maps; its ESCALATE sentinel means 'no auto
    fix_owner' here (self-pointing: attribution recorded, fix_owner omitted — A3)."""
    import uuid

    import route

    ss = env.get("stage_specific", {})
    if ss.get("analysis_state") != "complete":
        return "blocked", "skipped_reason", [], None
    root_cause = ss.get("root_cause")
    target = route.TRIAGE_ROOT_CAUSE.get(root_cause, route.ESCALATE)
    sim_hit = None
    for e in reversed(events):  # THIS run's own dispatch (not the latest triage dispatch,
        # which would mislabel subject.outcome_run when re-reaping an older run — F8b)
        if (
            e["type"] == "dispatch"
            and e["rule"] == "simulation-triage"
            and e["run"] == run
        ):
            sim_hit = e["params"].get("sim_run")
            break
    # Structural correlates live in the ADVISORY tier — stage_specific is
    # additionalProperties:false with no evidence/fix_locus keys, so the old
    # ss.get("evidence"/"fix_locus") reads were ALWAYS empty (D5). Map them: L2 repro
    # artifacts -> diagnosis.evidence (§3.4 "L2 repro 经 diagnosis.evidence 引用"), and
    # per-finding anchors -> fix_locus. The triage result.json is the always-present primary
    # evidence record.
    advisory = ss.get("advisory", {})
    triage_rj = str(Path(*rules.RULES["simulation-triage"].workdir_root) / "result.json")
    evidence = [triage_rj] + list(advisory.get("experiment", {}).get("artifacts", []))
    fix_locus = [f["anchor"] for f in advisory.get("findings", []) if f.get("anchor")]
    diagnosis = {
        "type": "diagnosis",
        "id": f"diag-{uuid.uuid4().hex[:12]}",
        "subject": {"proof": "simulation", "outcome_run": sim_hit},
        "attribution": root_cause,
        "fix_locus": fix_locus,
        "evidence": evidence,
        "confidence": ss.get("confidence"),
        "source": "triage",
    }
    if target != route.ESCALATE:
        diagnosis["fix_owner"] = target  # legality: target ∈ input_closure("simulation")
    # A complete triage is never a fail (spec §2 triage 无独立 fail 态): it mints no proof,
    # so its verdict is a plain non-blocked "pass" regardless of env["status"] (the envelope
    # schema permits status=fail, but a triage fail outcome would crash repair's proof scan).
    return "pass", None, [], diagnosis


def _graded(module, events, rule):
    """Oracle grade at reap (§5.4 ratchet): proposed unless a LIVE pin's recorded content
    fingerprint matches the oracle's CURRENT content. A pin is live iff NO reopen naming
    its oracle_ref appears AFTER it in event order — set-membership over refs would kill
    re-pinning forever (pin→reopen→pin must yield a live pin again)."""
    if rule.oracle[1] != "proposed":
        return rule.oracle[1]
    live = []
    for i, e in enumerate(events):
        if e["type"] == "pin" and e["oracle_ref"] == rule.oracle[0]:
            reopened_later = any(
                r["type"] == "reopen" and r["pin_ref"] == rule.oracle[0]
                for r in events[i + 1 :]
            )
            if not reopened_later:
                live.append(e)
    if not live:
        return "proposed"
    current = _oracle_content_fp(module, rule)
    if current == facts.UNKNOWN:
        return "proposed"  # unreadable oracle content never inherits trust
    # Compare against the LATEST live pin only (spec §5.4 "与最新 pin 记录比对"). `live` is in
    # event order, so live[-1] is the newest; an OLDER live pin matching current content must
    # not resurrect trust the newer endorsement moved on from.
    return "human" if live[-1]["content_fingerprint"] == current else "proposed"


def cmd_diagnose(
    module,
    diag_id,
    subject_proof,
    subject_run,
    attribution,
    fix_owner,
    fix_locus,
    evidence,
    confidence,
    provenance,
    supersedes,
):
    """Human-authored diagnosis (source="human"). Structural correlates enforced here
    at write time (§3.4), because the schema alone cannot express them:
    - fix_owner, when present, must be a real auto-rebuild target: a producer inside
      the TRANSITIVE input closure of subject_proof (rules.input_closure) — replaces
      the old is_dag_ancestor. Omitting fix_owner (self-pointing attribution) is
      always legal (P4): recorded as-is, disposition escalates it instead of
      auto-rebuilding.
    - provenance is required for source=human (the schema's `required` array cannot
      make a field conditionally required on another field's value)."""
    if fix_owner and fix_owner not in rules.input_closure(subject_proof):
        return {
            "ok": False,
            "error": f"fix_owner {fix_owner!r} not in input closure of {subject_proof!r}",
        }
    if not provenance:
        return {"ok": False, "error": "diagnose requires --provenance (source=human)"}
    ev = {
        "type": "diagnosis",
        "id": diag_id,
        "subject": {"proof": subject_proof, "outcome_run": subject_run},
        "attribution": attribution,
        "evidence": evidence or [],
        "source": "human",
        "provenance": provenance,
    }
    if fix_owner:
        ev["fix_owner"] = fix_owner
    if fix_locus:
        ev["fix_locus"] = fix_locus
    if confidence:
        ev["confidence"] = confidence
    if supersedes:
        ev["supersedes"] = supersedes
    facts.append_event(module, ev, _now())
    return {"ok": True, "id": diag_id}


def cmd_escalate(module, reason, open_question, candidates):
    ev = {"type": "escalation", "reason": reason, "open_question": open_question}
    if candidates:
        ev["candidates"] = candidates
    facts.append_event(module, ev, _now())
    return {"ok": True}


def cmd_epoch(module, objective, provenance, reason):
    ev = {
        "type": "epoch",
        "objective": objective,
        "provenance": provenance,
        "reason": reason,
    }
    facts.append_event(module, ev, _now())
    return {"ok": True}


def cmd_pin(module, rule, provenance, reason):
    r = rules.RULES[rule]
    if r.oracle_selector is None:
        grade = r.oracle[1] if r.oracle else None
        return {
            "ok": False,
            "error": f"{rule} has no oracle_selector (grade={grade!r}, not pinnable)",
        }
    fp = _oracle_content_fp(module, r)
    if fp == facts.UNKNOWN:
        # A pin must endorse REAL content (§5.4). A zero-match selector records
        # content_fingerprint="unknown" — an inert pin that can never grade human — yet
        # returns ok:true. Reject so the human learns nothing was pinned (conservative).
        return {
            "ok": False,
            "error": f"{rule} oracle selector {r.oracle_selector!r} matched no readable "
            "content (unknown fingerprint — nothing to pin)",
        }
    ev = {
        "type": "pin",
        "oracle_ref": r.oracle[0],
        "content_fingerprint": fp,
        "provenance": provenance,
        "reason": reason,
    }
    facts.append_event(module, ev, _now())
    return {"ok": True, "oracle_ref": r.oracle[0], "content_fingerprint": fp}


def cmd_reopen(module, pin_ref, reason):
    events = facts.read_events(module)
    # A reopen must revoke a real pin: pin_ref names a pinned oracle_ref (§5.4). A typo'd
    # ref would append a reopen that matches nothing — ok:true yet zero revocation, so the
    # human believes trust was withdrawn when it was not. Reject instead (conservative).
    if not any(
        e["type"] == "pin" and e["oracle_ref"] == pin_ref for e in events
    ):
        return {
            "ok": False,
            "error": f"reopen: no pin for oracle_ref {pin_ref!r} (nothing to revoke)",
        }
    ev = {"type": "reopen", "pin_ref": pin_ref, "reason": reason}
    facts.append_event(module, ev, _now())
    return {"ok": True, "pin_ref": pin_ref}


def cmd_status(module):
    events = facts.read_events(module)
    return {"module": module, "stages": facts.projection(module, events)}


def cmd_consequences(module, paths):
    """For each queried path, the currently-VALID proofs that would flip to invalid if
    that path's content changed — recomputed from the recorded input/output version
    tables of each proof's latest outcome (the same tables facts.proof_valid compares
    against disk), without touching disk."""
    events = facts.read_events(module)
    out: dict[str, list[str]] = {}
    for path in paths:
        affected = []
        for rule_name, r in rules.RULES.items():
            if not r.proof:
                continue
            hit = facts._proof_outcome(events, r.proof)
            if hit is None:
                continue
            _, outcome = hit
            proof = next(p for p in outcome["proofs"] if p["name"] == r.proof)
            touched = set(proof.get("inputs", {})) | set(outcome.get("outputs", {}))
            if path in touched and facts.proof_valid(module, events, r.proof):
                affected.append(r.proof)
        out[path] = affected
    return {"paths": out}


def main():
    p = argparse.ArgumentParser(prog="kernel.py")
    sub = p.add_subparsers(dest="verb", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--module", required=True)
    d.add_argument("--objective", default="delivery")
    d.add_argument("--conservative", action="store_true")
    d.add_argument("--wake", default=None)
    di = sub.add_parser("dispatch")
    di.add_argument("--module", required=True)
    di.add_argument("--rule", required=True, choices=list(rules.RULES))
    di.add_argument("--objective", default="delivery")
    di.add_argument("--conservative", action="store_true")
    di.add_argument("--directive", default=None)
    di.add_argument(
        "--diagnosis-refs",
        default=None,
        help="comma-separated diagnosis ids this auto-rebuild rests on (§1.4 audit)",
    )
    di.add_argument(
        "--params",
        default=None,
        help="JSON object merged into the dispatch event's params, e.g. "
        '--params \'{"sim_run": 5}\' (simulation-triage; rules.RULES[rule].params '
        "names what a rule expects)",
    )
    re_ = sub.add_parser("reap")
    re_.add_argument("--module", required=True)
    re_.add_argument("--rule", required=True, choices=list(rules.RULES))
    re_.add_argument("--run", required=True, type=int)
    re_.add_argument(
        "--subagent-output-file",
        default=None,
        help="/tmp/.../tasks/<agent_id>.output path from the async Task "
        "launch, best-effort mirrored to <workdir>/.subagent_traces/",
    )
    dg = sub.add_parser("diagnose")
    dg.add_argument("--module", required=True)
    dg.add_argument("--id", required=True, dest="diag_id")
    dg.add_argument("--subject-proof", required=True, choices=rules.FORWARD_PRIORITY)
    dg.add_argument("--subject-run", required=True, type=int)
    dg.add_argument("--attribution", required=True)
    dg.add_argument("--fix-owner", default=None, choices=rules.FORWARD_PRIORITY)
    dg.add_argument("--fix-locus", nargs="+", default=None)
    dg.add_argument("--evidence", nargs="+", required=True)
    dg.add_argument("--confidence", default=None, choices=["high", "medium", "low"])
    dg.add_argument("--provenance", required=True)
    dg.add_argument("--supersedes", default=None)
    es = sub.add_parser("escalate")
    es.add_argument("--module", required=True)
    es.add_argument("--reason", required=True)
    es.add_argument("--open-question", required=True)
    es.add_argument(
        "--candidates", default=None, help="JSON array of candidate objects"
    )
    ep = sub.add_parser("epoch")
    ep.add_argument("--module", required=True)
    ep.add_argument("--objective", required=True)
    ep.add_argument("--provenance", required=True)
    ep.add_argument("--reason", required=True)
    pn = sub.add_parser("pin")
    pn.add_argument("--module", required=True)
    pn.add_argument("--rule", required=True, choices=list(rules.RULES))
    pn.add_argument("--provenance", required=True)
    pn.add_argument("--reason", required=True)
    ro = sub.add_parser("reopen")
    ro.add_argument("--module", required=True)
    ro.add_argument("--pin-ref", required=True)
    ro.add_argument("--reason", required=True)
    st = sub.add_parser("status")
    st.add_argument("--module", required=True)
    st.add_argument(
        "--json",
        action="store_true",
        help="accepted for CLI symmetry — every verb already prints a "
        "JSON envelope, so this is a no-op",
    )
    co = sub.add_parser("consequences")
    co.add_argument("--module", required=True)
    co.add_argument("--paths", nargs="+", required=True)
    args = p.parse_args()
    refs = (
        args.diagnosis_refs.split(",")
        if getattr(args, "diagnosis_refs", None)
        else None
    )
    candidates = None
    if getattr(args, "candidates", None):
        try:
            candidates = json.loads(args.candidates)
        except json.JSONDecodeError as e:
            print(
                json.dumps(
                    {"ok": False, "error": f"--candidates JSON parse error: {e}"},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
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
            objective=args.objective,
            conservative=args.conservative,
        ),
        "dispatch": lambda: cmd_dispatch(
            args.module,
            args.rule,
            args.objective,
            args.conservative,
            args.directive,
            refs,
            extra_params,
        ),
        "reap": lambda: cmd_reap(
            args.module, args.rule, args.run, args.subagent_output_file
        ),
        "diagnose": lambda: cmd_diagnose(
            args.module,
            args.diag_id,
            args.subject_proof,
            args.subject_run,
            args.attribution,
            args.fix_owner,
            args.fix_locus,
            args.evidence,
            args.confidence,
            args.provenance,
            args.supersedes,
        ),
        "escalate": lambda: cmd_escalate(
            args.module, args.reason, args.open_question, candidates
        ),
        "epoch": lambda: cmd_epoch(
            args.module, args.objective, args.provenance, args.reason
        ),
        "pin": lambda: cmd_pin(args.module, args.rule, args.provenance, args.reason),
        "reopen": lambda: cmd_reopen(args.module, args.pin_ref, args.reason),
        "status": lambda: cmd_status(args.module),
        "consequences": lambda: cmd_consequences(args.module, args.paths),
    }
    print(json.dumps(handlers[args.verb](), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
