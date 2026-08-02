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
    diagnosis_refs,
    extra_params=None,
    caused_by=None,
):
    """Re-checks dispatchability AT THIS INSTANT (decide→dispatch drift guard, §4.2):
    in-flight premise and input availability.

    The signoff gate is not among these checks — signoff is not dispatchable. `cmd_signoff`
    runs it (§5.5).

    extra_params (parsed --params JSON object, e.g. {"sim_run": 5} for simulation-triage
    per rules.RULES[rule].params) is merged into the recorded dispatch event's `params`
    (Task C7 — the generic complement to schedule.py's disposition, which already computes
    {"sim_run": <run>} for triage but had no CLI path to land it on the actual dispatch
    event).

    caused_by is the list of (rule, run) failures this dispatch answers, from --caused-by.
    It is what makes a dispatch a rework: the kernel resolves each to that run's own
    result.json and names it in dispatch.json, so the fix owner reads the failing envelope
    at a kernel-given path rather than navigating to it."""
    events = facts.read_events(module)
    if any(f["rule"] == rule for f in facts.in_flight(events)):
        return {"ok": False, "error": f"{rule} already in-flight"}
    if not facts.rule_available(module, events, rule):
        return {"ok": False, "error": f"{rule} inputs not available"}
    # Mandatory declared params must be supplied via --params. Missing them mints a
    # malformed event downstream: a triage without sim_run derives a diagnosis with
    # subject.outcome_run=None -> schema violation AFTER the outcome already landed ->
    # half-reap (F8a). Reject up front.
    missing = [
        p for p in rules.RULES[rule].params if not (extra_params and p in extra_params)
    ]
    if missing:
        return {
            "ok": False,
            "error": f"{rule} dispatch missing required --params {missing} "
            f"(Rule.params={list(rules.RULES[rule].params)})",
        }
    root = facts.module_root(module)
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
    # A named diagnosis carries the two things no envelope holds: where its author says the
    # fix lands, and (human-authored only) the reasoning behind it. An unknown ref would
    # drop both silently, which is exactly the silent loss §3.3 forbids — reject instead.
    by_id = {e["id"]: e for e in events if e["type"] == "diagnosis"}
    scope = facts.stale_inputs(module, events, rule)
    reasons = []
    for ref in diagnosis_refs or []:
        diag = by_id.get(ref)
        if diag is None:
            return {"ok": False, "error": f"unknown diagnosis ref {ref!r}"}
        scope += [a for a in diag.get("fix_locus", []) if a not in scope]
        if diag["source"] == "human" and diag.get("reason"):
            reasons.append(diag["reason"])
    run = facts.runs_of(events, rule) + 1
    workdir = str(Path(*rules.workdir_root(rule), "runs", str(run)))
    (root / workdir).mkdir(parents=True, exist_ok=True)
    abs_workdir = root / workdir
    store.carry_self(module, rule, abs_workdir)  # self-carry (no-op unless Rule.carry)
    store.write_dispatch(
        module, rule, abs_workdir, extra_params, scope, caused_by_paths, reasons
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
    facts.append_event(module, ev, _now())
    return {
        "ok": True,
        "rule": rule,
        "run": run,
        "workdir": workdir,
        "skill": rules.RULES[rule].skill,
        "execution": rules.RULES[rule].execution,
    }


def cmd_reap(module, rule, run):
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
        # The installed plugin directory is not a git checkout, so this exits 128 with an
        # empty stdout — the deployment where the key matters most. Write it only when git
        # actually answered: a missing key reads as "no identity recorded", while the empty
        # string it used to store is indistinguishable in the log from a recorded value.
        if p.returncode == 0 and p.stdout.strip():
            ids["plugin"] = p.stdout.strip()
    except OSError:
        pass  # best-effort: absence never blocks a reap
    return ids


def _stale_result_reason(produced_at, dispatch_ts) -> str | None:
    """Temporal integrity of a reaped verdict (§5.6): result.json must have been authored
    by THIS run's executor, so its produced_at must not predate the run's own dispatch —
    an older stamp means a carried-in stale envelope (e.g. a prior canonical result.json
    copied into the workdir), which must never mint an outcome. The dispatch ts is floored
    to whole seconds before comparing: skill finalizers stamp second-resolution UTC while
    the kernel stamps microseconds, and a sub-second run must not be misjudged stale.
    Unparseable produced_at blocks too (conservative — the envelope contract mandates
    ISO-8601, stage-subagent.md.tpl); a naive timestamp is taken as UTC."""

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


def _derive_verdict(module, rule_name, run, rj: Path, events):
    """UNIFORM return: (verdict, reason, proofs, diagnosis) — proofs is [] and diagnosis
    is None whenever not applicable; the shape NEVER varies by rule kind. result.json
    status -> verdict; missing/unparseable/malformed/schema-violation/stale -> blocked
    (stale = produced_at predates this run's dispatch, _stale_result_reason). For
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
    # Temporal integrity for EVERY rule kind (proof, triage, none) — the dispatch event
    # exists by cmd_reap's guard. A re-reap of an old run compares against that run's OWN
    # dispatch, so the crash-repair and pin-regrade paths are unaffected.
    dispatch = next(
        e
        for e in reversed(events)
        if e["type"] == "dispatch" and e["rule"] == rule_name and e["run"] == run
    )
    stale = _stale_result_reason(env.get("produced_at"), dispatch["ts"])
    if stale:
        return "blocked", stale, [], None
    if rule_name == "simulation-triage":
        return _derive_triage(env, dispatch)  # Task C7 — same 4-tuple
    if rule.proof is None:
        return status, None, [], None
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
        "oracle": {
            "ref": rule.oracle[0],
            "grade": facts.oracle_grade(module, events, rule),
        },
        "evidence": evidence,
    }
    return status, None, [proof], None


def _derive_triage(env, dispatch):
    """Triage reap (§2 triage contract): complete -> (verdict, None, [], diagnosis-event);
    skipped/crash -> blocked, no diagnosis (the sim failure stays ambiguous; next round
    re-dispatches triage, §3.3). Confidence lands as-is (P4) — reliability is decide's
    gate, not a reap branch. `root_cause` IS the rule name, so no map decodes it: it
    becomes `fix_owner` when it is a legal auto-rebuild target, and a self-pointing
    attribution (root_cause == the failing rule) is outside simulation's input closure by
    construction, so it lands recorded-but-unroutable (A3).
    `dispatch` is THIS run's own dispatch event, located once in _derive_verdict (not
    the latest triage dispatch, which would mislabel subject.outcome_run when
    re-reaping an older run — F8b)."""
    import uuid

    ss = env.get("stage_specific", {})
    if ss.get("analysis_state") != "complete":
        return "blocked", "skipped_reason", [], None
    root_cause = ss.get("root_cause")
    sim_hit = dispatch["params"].get("sim_run")
    # Structural correlates live in the ADVISORY tier — stage_specific is
    # additionalProperties:false with no evidence/fix_locus keys, so the old
    # ss.get("evidence"/"fix_locus") reads were ALWAYS empty (D5). Map them: the
    # experiment's artifacts -> diagnosis.evidence, and per-finding anchors -> fix_locus. The triage result.json is the always-present primary
    # evidence record.
    #
    # Every entry is anchored on THIS triage run's own directory, which makes the list
    # single-basis (module-relative throughout) and immutable: `advisory.experiment
    # .artifacts[]` are workdir-relative by the triage skill's contract, and canonical
    # result.json is overwritten by the next triage while runs/<N>/ persists. A later
    # triage therefore cannot move the evidence a landed diagnosis rests on.
    advisory = ss.get("advisory", {})
    triage_run = (
        Path(*rules.RULES["simulation-triage"].workdir_root)
        / "runs"
        / str(dispatch["run"])
    )
    evidence = [str(triage_run / "result.json")] + [
        str(triage_run / a) for a in advisory.get("experiment", {}).get("artifacts", [])
    ]
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
    if root_cause in rules.input_closure("simulation"):
        diagnosis["fix_owner"] = root_cause
    # A complete triage is never a fail (spec §2 triage 无独立 fail 态): it mints no proof,
    # so its verdict is a plain non-blocked "pass" regardless of env["status"] (the envelope
    # schema permits status=fail, but a triage fail outcome would crash repair's proof scan).
    return "pass", None, [], diagnosis


# Oracle grade derivation (proposed/human ratchet) lives in facts.oracle_grade /
# facts.oracle_content_fp — read LIVE by both the reap-time outcome record and the signoff
# gate, so a post-reap pin/reopen takes effect without a re-reap.


def _module_relative(module, s):
    """An absolute path under the module root becomes module-relative. Anything else — an
    already-relative path, or a `<file>:<line>` anchor — is left alone. Both fix_locus and
    evidence reach dispatch.json, where a mixed-basis list would be unreadable."""
    if not s.startswith("/"):
        return s
    try:
        return str(Path(s).resolve().relative_to(facts.module_root(module).resolve()))
    except ValueError:
        return s


def cmd_diagnose(
    module,
    diag_id,
    subject_proof,
    subject_run,
    attribution,
    fix_owner,
    fix_locus,
    evidence,
    provenance,
    reason,
    supersedes,
):
    """Human-authored diagnosis (source="human"). Structural correlates enforced here
    at write time (§3.4), because the schema alone cannot express them:
    - fix_owner, when present, must be a real auto-rebuild target: a producer inside
      the TRANSITIVE input closure of subject_proof (rules.input_closure) — replaces
      the old is_dag_ancestor. Omitting fix_owner (self-pointing attribution) is
      always legal (P4): recorded as-is, disposition escalates it instead of
      auto-rebuilding.
    - provenance and reason are both required for source=human (the schema's `required`
      array cannot make a field conditionally required on another field's value).
      provenance is the bare identity that vouches; reason is the reasoning, and it is
      what dispatch.json carries verbatim to the fix owner."""
    if fix_owner and fix_owner not in rules.input_closure(subject_proof):
        return {
            "ok": False,
            "error": f"fix_owner {fix_owner!r} not in input closure of {subject_proof!r}",
        }
    if not provenance:
        return {"ok": False, "error": "diagnose requires --provenance (source=human)"}
    if not reason or not reason.strip():
        return {"ok": False, "error": "diagnose requires --reason (source=human)"}
    ev = {
        "type": "diagnosis",
        "id": diag_id,
        "subject": {"proof": subject_proof, "outcome_run": subject_run},
        "attribution": attribution,
        "evidence": [_module_relative(module, e) for e in evidence or []],
        "source": "human",
        "provenance": provenance,
        "reason": reason,
    }
    if fix_owner:
        ev["fix_owner"] = fix_owner
    if fix_locus:
        ev["fix_locus"] = [_module_relative(module, a) for a in fix_locus]
    if supersedes:
        ev["supersedes"] = supersedes
    facts.append_event(module, ev, _now())
    return {"ok": True, "id": diag_id}


def cmd_pin(module, rule, provenance, reason):
    r = rules.RULES[rule]
    if r.oracle_selector is None:
        grade = r.oracle[1] if r.oracle else None
        return {
            "ok": False,
            "error": f"{rule} has no oracle_selector (grade={grade!r}, not pinnable)",
        }
    fp = facts.oracle_content_fp(module, r)
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
    if not any(e["type"] == "pin" and e["oracle_ref"] == pin_ref for e in events):
        return {
            "ok": False,
            "error": f"reopen: no pin for oracle_ref {pin_ref!r} (nothing to revoke)",
        }
    ev = {"type": "reopen", "pin_ref": pin_ref, "reason": reason}
    facts.append_event(module, ev, _now())
    return {"ok": True, "pin_ref": pin_ref}


def cmd_signoff(module, provenance, reason):
    """Close signoff: run the gate, and only if it is clear record the human act (§5.5).

    The third ask-gated judgment verb, beside pin/reopen — and the only bypass surface the
    gate has, which is why the gate runs HERE rather than being trusted from a prior
    `decide`. A caller that skips decide entirely still cannot mint a signoff (§6's
    bypass-blocked test targets exactly this)."""
    events = facts.read_events(module)
    reason_blocked = facts.signoff_gate(module, events)
    if reason_blocked is not None:
        return {"ok": False, "error": reason_blocked}
    # basis BEFORE the append: what is being endorsed is the state the gate just cleared,
    # not the state that includes the endorsement.
    basis = facts.signoff_basis(module, events)
    ev = {"type": "signoff", "provenance": provenance, "reason": reason}
    facts.append_event(module, ev, _now())
    return {
        "ok": True,
        "module": module,
        "provenance": provenance,
        "basis": basis,
    }


def cmd_status(module):
    events = facts.read_events(module)
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
    d.add_argument("--wake", default=None)
    d.add_argument(
        "--closing",
        action="store_true",
        help="arm the signoff gate at DONE and return what it clears (facts.signoff_basis); "
        "a blocked gate comes back as ESCALATE. Which proofs are required is unaffected.",
    )
    di = sub.add_parser("dispatch")
    di.add_argument("--module", required=True)
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
        help="comma-separated diagnosis ids this auto-rebuild rests on (§1.4 audit)",
    )
    di.add_argument(
        "--params",
        default=None,
        help="JSON object merged into the dispatch event's params, e.g. "
        "--params '{\"sim_run\": 5}' (simulation-triage; rules.RULES[rule].params "
        "names what a rule expects)",
    )
    re_ = sub.add_parser("reap")
    re_.add_argument("--module", required=True)
    re_.add_argument("--rule", required=True, choices=list(rules.RULES))
    re_.add_argument("--run", required=True, type=int)
    dg = sub.add_parser("diagnose")
    dg.add_argument("--module", required=True)
    dg.add_argument("--id", required=True, dest="diag_id")
    dg.add_argument("--subject-proof", required=True, choices=rules.FORWARD_PRIORITY)
    dg.add_argument("--subject-run", required=True, type=int)
    dg.add_argument("--attribution", required=True)
    dg.add_argument("--fix-owner", default=None, choices=rules.FORWARD_PRIORITY)
    dg.add_argument("--fix-locus", nargs="+", default=None)
    dg.add_argument("--evidence", nargs="+", required=True)
    dg.add_argument("--provenance", required=True)
    dg.add_argument("--reason", required=True)
    dg.add_argument("--supersedes", default=None)
    pn = sub.add_parser("pin")
    pn.add_argument("--module", required=True)
    pn.add_argument("--rule", required=True, choices=list(rules.RULES))
    pn.add_argument("--provenance", required=True)
    pn.add_argument("--reason", required=True)
    ro = sub.add_parser("reopen")
    ro.add_argument("--module", required=True)
    ro.add_argument("--pin-ref", required=True)
    ro.add_argument("--reason", required=True)
    so = sub.add_parser("signoff")
    so.add_argument("--module", required=True)
    so.add_argument("--provenance", required=True)
    so.add_argument("--reason", required=True)
    st = sub.add_parser("status")
    st.add_argument("--module", required=True)
    co = sub.add_parser("consequences")
    co.add_argument("--module", required=True)
    co.add_argument("--paths", nargs="+", required=True)
    args = p.parse_args()
    # Every verb is module-scoped, and module paths are resolved relative to the CURRENT
    # WORKING DIRECTORY (facts.module_root). A missing module directory is therefore always
    # an error and never a legitimate starting state: brainstorm.md is a PIPELINE_INPUT that
    # must already exist for `specification` to be dispatchable at all, so a module with no
    # directory can never become schedulable. Without this, the wrong cwd produced two
    # answers that both looked like real ones — `status` inventing an all-`missing`
    # projection at exit 0, and `decide` returning the same "no eligible rule" ESCALATE a
    # genuinely deadlocked module returns. Name the resolved absolute path: that is what
    # makes a cwd mistake visible.
    root = facts.module_root(args.module)
    if not root.is_dir():
        sys.exit(
            f"kernel.py {args.verb}: no module directory at {root.resolve()} "
            f"(module paths resolve against the current working directory)"
        )
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
            args.fix_locus,
            args.evidence,
            args.provenance,
            args.reason,
            args.supersedes,
        ),
        "pin": lambda: cmd_pin(args.module, args.rule, args.provenance, args.reason),
        "reopen": lambda: cmd_reopen(args.module, args.pin_ref, args.reason),
        "signoff": lambda: cmd_signoff(args.module, args.provenance, args.reason),
        "status": lambda: cmd_status(args.module),
        "consequences": lambda: cmd_consequences(args.module, args.paths),
    }
    print(json.dumps(handlers[args.verb](), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
