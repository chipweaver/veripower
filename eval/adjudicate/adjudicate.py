"""RTL -> signoff-clean adjudication harness (P0 workstream (3)).

The arm-blind, two-arm-symmetric judge that `aggregate.py` leaves a hole for
(its rows carry `pass_at_1: None`, "joined later once the arm-blind
adjudication harness (workstream (3)) lands"). Given ONE arm's FINAL RTL, it
applies the fixed §1.3 signoff bar and emits a quality row keyed the same way
aggregate.py keys its cost rows — (arm, design, seed, module) — so the two
join into the final Pareto table.

signoff-clean = FOUR criteria AND'd (§1.3):
  (a) golden   — independent held-out golden passes (design-specific, NOT here)
  (b) lint     — SpyGlass lint clean
  (c) cdc      — SpyGlass CDC clean
  (d) timing   — DC synth completes AND PT STA setup/hold WNS >= 0

Two invariants this harness exists to enforce — do not weaken them:

  SYMMETRY (§1.3). Both arms' final RTL are judged with the SAME FIXED spec
  constraints — clock target (.sdc), lint/cdc ruleset (.sgdc), golden +
  tolerance — supplied via --fixed. NEVER the arm's own self-written
  SDC/waivers (else a lax constraint buys a free timing pass). The tool layer
  is the arm-neutral b1-wrapper (--wrapper): its scripts/*.tcl are reused
  verbatim; only design/arm-specific inputs (rtl filelist, fixed constraints,
  generated .prj top) are overridden per run.

  ARM-BLIND. The verdict is a pure function of (rtl filelist, fixed inputs,
  top). This module never reads full's events.jsonl or B1's transcript — cost
  attribution lives in aggregate.py; keeping them separate is what makes the
  judge blind to which arm it is scoring.

  FAIL-LOUD (mirrors docs/eda-env.md parse_coverage posture). A criterion is
  clean ONLY on positive evidence it passed. Tool did not run to completion,
  report missing, WNS parser does not recognize the format -> NOT clean, and
  `adjudication_partial=True`. This harness never fabricates a "clean" result.

Run:  python eval/adjudicate/adjudicate.py \
          --arm full --design flash_attn --seed 1 \
          --rtl-sourcelist <arm_rtl_sourcelist> --fixed eval/fixed/flash_attn/ \
          --top <TOP> --out eval/runs/adj-flash_attn
Writes <out>.json / <out>.csv (one row per invocation; re-run per arm/seed and
concatenate, or point --out at the same prefix with --append).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
_DEFAULT_WRAPPER = _REPO_ROOT / "eval" / "b1-wrapper"

# The four signoff-clean criteria (§1.3), in report order. signoff_clean is
# their strict AND — any None/False (incl. fail-loud unknowns) fails the AND.
_CRITERIA = ("golden", "lint", "cdc", "timing_met")


# --------------------------------------------------------------------------- #
# sandbox: per-run workdir that reuses the b1-wrapper tool layer unchanged     #
# --------------------------------------------------------------------------- #
def _prepare_workdir(
    workdir: Path,
    wrapper: Path,
    rtl_sourcelist_lines: list[str],
    fixed_dir: Path,
    top: str,
    lib_db: str,
) -> Path:
    """Build a self-contained sandbox so `make -C workdir` drives the wrapper
    tools against THIS arm's RTL under the FIXED constraints. Overrides exactly
    the design/arm-specific inputs; every scripts/*.tcl is symlinked verbatim
    from the wrapper (identical tool invocation across arms).

    Layout produced:
      workdir/
        Makefile              -> symlink wrapper/Makefile
        env.sh                (generated: TOP/LIB_DB/NETLIST/SDC)
        filelist.txt          <- arm RTL-only sourcelist (feeds lint/cdc AND synth)
        constraints/design.sdc  <- FIXED (fixed_dir/design.sdc)
        constraints/design.sgdc <- FIXED (fixed_dir/design.sgdc)
        scripts/dc_run.tcl      -> symlink wrapper
        scripts/run_sta.tcl     -> symlink wrapper
        scripts/run_spyglass.tcl-> symlink wrapper
        scripts/spyglass.prj    (generated: top + fixed sgdc + arm sourcelist)
    """
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "scripts").mkdir(exist_ok=True)
    (workdir / "constraints").mkdir(exist_ok=True)

    def _link(src: Path, dst: Path) -> None:
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src.resolve())

    _link(wrapper / "Makefile", workdir / "Makefile")
    for tcl in ("dc_run.tcl", "run_sta.tcl", "run_spyglass.tcl"):
        _link(wrapper / "scripts" / tcl, workdir / "scripts" / tcl)

    # RTL-only sourcelist (synthesizable RTL, one path per line; no TB, no UVM,
    # no +incdir). This SINGLE list feeds BOTH lint/cdc (SpyGlass sourcelist) AND
    # synth (DC FILELIST): adjudication never runs sim, so the sim manifest
    # (filelist.f — which carries TB + UVM) is neither needed nor wanted here;
    # feeding a TB to synth or lint corrupts the verdict. The caller resolves
    # these lines (explicit --rtl-sourcelist preferred; derive-from-manifest is a
    # warned fallback — see _resolve_sourcelist).
    (workdir / "filelist.txt").write_text("\n".join(rtl_sourcelist_lines) + "\n")

    # FIXED constraints — the crux of §1.3 symmetry. Copied from --fixed, never
    # taken from the arm. Missing here is fatal (a run with no fixed bar cannot
    # be adjudicated) — surface it, do not silently fall back to the wrapper's
    # generic example.{sdc,sgdc}.
    for name in ("design.sdc", "design.sgdc"):
        src = fixed_dir / name
        if not src.exists():
            raise FileNotFoundError(
                f"fixed constraint missing: {src} — cannot adjudicate without "
                f"the pre-registered §1.3 fixed bar"
            )
        shutil.copyfile(src, workdir / "constraints" / name)

    (workdir / "env.sh").write_text(_gen_env_sh(top, lib_db))
    (workdir / "scripts" / "spyglass.prj").write_text(_gen_spyglass_prj(top))
    return workdir


def _gen_env_sh(top: str, lib_db: str) -> str:
    # NETLIST/SDC point at the DC products STA consumes. SDC here is the OUTPUT
    # netlist sdc DC writes — distinct from SDC_IN (the fixed timing intent DC
    # reads), which we pass on the synth command line.
    return (
        "# generated by adjudicate.py — do not edit\n"
        f'export TOP="{top}"\n'
        f'export LIB_DB="{lib_db}"\n'
        'export NETLIST="out/${TOP}_syn.v"\n'
        'export SDC="out/${TOP}_syn.sdc"\n'
    )


def _gen_spyglass_prj(top: str) -> str:
    # Same options as the wrapper prj, but top + fixed sgdc are substituted.
    return (
        "#!SPYGLASS_PROJECT_FILE\n"
        "#!VERSION 3.0\n"
        "read_file -type sourcelist filelist.txt\n"
        "read_file -type sgdc       constraints/design.sgdc\n"
        "set_option projectwdir                 ./spyglass_work\n"
        "set_option language_mode               mixed\n"
        "set_option designread_enable_synthesis no\n"
        "set_option enableSV                    yes\n"
        "set_option enableSV09                  yes\n"
        f"set_option top                         {top}\n"
    )


def _resolve_sourcelist(args) -> list[str]:
    """Resolve the arm's RTL-only sourcelist for lint/cdc + synth.

    Prefer --rtl-sourcelist (the wrapper's filelist.txt: synthesizable RTL only,
    which is exactly what lint/cdc and synth both consume). Fall back to deriving
    it from a --rtl VCS/DC manifest by dropping blank/#/-/+/$ lines — but a
    testbench .sv carries no distinguishing prefix and cannot be auto-excluded,
    so this path warns loudly: a TB leaking into synth/lint silently corrupts the
    verdict.
    """
    if args.rtl_sourcelist:
        return [
            ln.strip()
            for ln in Path(args.rtl_sourcelist).read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    if args.rtl:
        lines = [
            ln.strip()
            for ln in Path(args.rtl).read_text().splitlines()
            if ln.strip() and not ln.strip().startswith(("#", "-", "+", "$"))
        ]
        sys.stderr.write(
            "adjudicate: WARNING — deriving the RTL sourcelist from --rtl (a sim "
            "manifest). A testbench .sv cannot be auto-excluded and would corrupt "
            "lint/synth. Pass --rtl-sourcelist (RTL only) for a trustworthy "
            "verdict.\n"
        )
        return lines
    raise SystemExit("adjudicate: one of --rtl-sourcelist / --rtl is required")


# --------------------------------------------------------------------------- #
# tool driver                                                                  #
# --------------------------------------------------------------------------- #
def _make(
    target: str,
    workdir: Path,
    extra_env: dict | None = None,
    make_vars: dict | None = None,
    dry: bool = False,
) -> int:
    """Run one wrapper `make` target in the sandbox; returns the exit code.
    make_vars become `KEY=VALUE` command-line arguments — GNU make exports
    command-line variables into the recipe environment, so the wrapper's tcl
    scripts read them via $::env (e.g. FILELIST / SDC_IN in dc_run.tcl).
    In --dry-run, does not launch tools (returns 0) — lets the operator smoke
    the wiring on a host without EDA licenses."""
    if dry:
        return 0
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    argv = ["make", target]
    if make_vars:
        argv += [f"{k}={v}" for k, v in make_vars.items()]
    proc = subprocess.run(  # noqa: S603
        argv,
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
    )
    (workdir / f"{target}.adjlog").write_text(proc.stdout + "\n" + proc.stderr)
    return proc.returncode


# --------------------------------------------------------------------------- #
# per-criterion checks (each: positive evidence -> clean, else fail-loud)      #
# --------------------------------------------------------------------------- #
def check_lint(workdir: Path, dry: bool) -> dict:
    return _spyglass_check(workdir, "lint", dry)


def check_cdc(workdir: Path, dry: bool) -> dict:
    return _spyglass_check(workdir, "cdc", dry)


def _spyglass_check(workdir: Path, stage: str, dry: bool) -> dict:
    rc = _make(stage, workdir, extra_env={"SPYGLASS_STAGE": stage}, dry=dry)
    if dry:
        return {"clean": None, "ran": False, "reason": "dry-run"}
    if rc != 0:
        return {"clean": False, "ran": True, "reason": f"make {stage} rc={rc}"}
    # TODO(deploy): parse the SpyGlass moresimple report under
    # spyglass_work/<goal>/... and count violations at the severities the
    # pre-registered ruleset treats as blocking (Fatal/Error, plus any Warning
    # promoted by the fixed .sgdc). clean == (blocking count == 0). Report
    # location + severity policy are ruleset-version-specific; on a missing or
    # unrecognized report, return clean=False (fail-loud), NOT clean=True.
    report = _find_spyglass_report(workdir, stage)
    if report is None:
        return {
            "clean": False,
            "ran": True,
            "reason": f"{stage} report not found (fail-loud)",
        }
    violations = _count_spyglass_violations(report)  # TODO: real parser
    return {
        "clean": violations == 0,
        "ran": True,
        "violations": violations,
        "evidence": str(report),
    }


def _find_spyglass_report(workdir: Path, stage: str) -> Path | None:
    # TODO(deploy): pin the exact moresimple.rpt path per goal for the site's
    # SpyGlass version. Placeholder glob:
    hits = sorted((workdir / "spyglass_work").rglob("moresimple.rpt"))
    return hits[0] if hits else None


def _count_spyglass_violations(report: Path) -> int:
    # TODO(deploy): real severity-aware count. Placeholder returns a sentinel
    # that fails the AND so an unimplemented parser can never mint a pass.
    raise NotImplementedError(
        "SpyGlass violation parser not implemented — wire to the site's "
        "moresimple.rpt severity columns before running for score"
    )


def check_synth_timing(workdir: Path, dry: bool) -> dict:
    """(d): DC synth under FIXED SDC_IN, then PT STA; met == synth produced a
    netlist AND STA ran AND no VIOLATED slack (setup & hold WNS >= 0)."""
    sdc_in = "constraints/design.sdc"  # FIXED timing intent (not the arm's)
    # Synthesize the RTL-only sourcelist (filelist.txt), NOT the sim manifest —
    # dc_run.tcl analyzes every listed file, so a TB/UVM line would break synth.
    rc_synth = _make(
        "synth",
        workdir,
        make_vars={"FILELIST": "filelist.txt", "SDC_IN": sdc_in},
        dry=dry,
    )
    if dry:
        return {"timing_met": None, "synth_ok": None, "ran": False, "reason": "dry-run"}
    netlist = workdir / "out" / (_read_top(workdir) + "_syn.v")
    synth_ok = rc_synth == 0 and netlist.exists()
    if not synth_ok:
        return {
            "timing_met": False,
            "synth_ok": False,
            "ran": True,
            "reason": f"synth rc={rc_synth} / netlist present={netlist.exists()}",
        }
    rc_sta = _make("sta", workdir, dry=dry)
    report = workdir / "timing-report.txt"
    if rc_sta != 0 or not report.exists():
        return {
            "timing_met": False,
            "synth_ok": True,
            "ran": True,
            "reason": f"sta rc={rc_sta} / report present={report.exists()}",
        }
    wns = _parse_wns(report.read_text())
    if wns is None:
        # parser did not recognize the format -> cannot confirm met -> fail-loud
        return {
            "timing_met": False,
            "synth_ok": True,
            "ran": True,
            "reason": "WNS parse unrecognized (fail-loud)",
            "evidence": str(report),
        }
    met = wns["setup_ns"] >= 0 and wns["hold_ns"] >= 0
    return {
        "timing_met": met,
        "synth_ok": True,
        "ran": True,
        "wns_setup_ns": wns["setup_ns"],
        "wns_hold_ns": wns["hold_ns"],
        "evidence": str(report),
    }


def _read_top(workdir: Path) -> str:
    for ln in (workdir / "env.sh").read_text().splitlines():
        if ln.startswith("export TOP="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("TOP not found in generated env.sh")


def _parse_wns(report_text: str) -> dict | None:
    """Extract worst setup/hold slack from run_sta.tcl's report
    (report_timing -delay max, then -delay min, then check_timing).

    TODO(deploy): this is tool-version-sensitive (mirrors eda-env.md's stance
    on urg text layout). The robust gate is 'any VIOLATED slack -> not met';
    the numeric WNS below is best-effort for reporting. Attributing a given
    slack line to setup vs hold relies on run_sta.tcl's max-then-min ordering —
    verify against your PT version's exact 'slack (MET|VIOLATED)  <val>' lines
    before trusting the numbers. Return None on any unrecognized layout so the
    caller fails loud rather than assuming met.
    """
    raise NotImplementedError(
        "WNS parser not implemented — wire to the site's PrimeTime "
        "report_timing slack layout before running for score"
    )


def check_golden(
    golden_verdict: str | None, golden_cmd: str | None, workdir: Path, dry: bool
) -> dict:
    """(a): the independent, held-out golden (§1.4). This harness does NOT own
    a golden — the b1-wrapper deliberately ships none, and the golden is
    authored by an independent party and held out during iteration. Supply the
    result one of two ways:
      --golden-verdict {pass,fail}  operator ran the manual golden (§1.3
                                     '手动 golden'), records the outcome.
      --golden-cmd "<cmd>"          optional hook: run an external golden
                                     checker in the sandbox; exit 0 == pass.
    Neither given -> None -> signoff_clean cannot be True (correct: no golden
    evidence means not proven functional).
    """
    if golden_verdict is not None:
        return {
            "golden": golden_verdict == "pass",
            "ran": True,
            "source": "manual-verdict",
        }
    if golden_cmd:
        if dry:
            return {"golden": None, "ran": False, "reason": "dry-run"}
        proc = subprocess.run(  # noqa: S602
            golden_cmd,
            cwd=str(workdir),
            shell=True,
            capture_output=True,
            text=True,
        )
        (workdir / "golden.adjlog").write_text(proc.stdout + "\n" + proc.stderr)
        return {
            "golden": proc.returncode == 0,
            "ran": True,
            "source": "golden-cmd",
            "rc": proc.returncode,
        }
    return {"golden": None, "ran": False, "reason": "no golden verdict/cmd supplied"}


# --------------------------------------------------------------------------- #
# assemble one quality row (join key identical to aggregate.py)                #
# --------------------------------------------------------------------------- #
def adjudicate_run(args) -> dict:
    workdir = (
        Path(args.workdir)
        if args.workdir
        else (
            _REPO_ROOT
            / "eval"
            / "runs"
            / "adj"
            / args.design
            / args.arm
            / f"seed{args.seed}"
        )
    )
    _prepare_workdir(
        workdir=workdir,
        wrapper=Path(args.wrapper),
        rtl_sourcelist_lines=_resolve_sourcelist(args),
        fixed_dir=Path(args.fixed),
        top=args.top,
        lib_db=args.lib_db or os.environ.get("LIB_DB", ""),
    )

    golden = check_golden(args.golden_verdict, args.golden_cmd, workdir, args.dry_run)
    lint = check_lint(workdir, args.dry_run)
    cdc = check_cdc(workdir, args.dry_run)
    timing = check_synth_timing(workdir, args.dry_run)

    vals = {
        "golden": golden.get("golden"),
        "lint": lint.get("clean"),
        "cdc": cdc.get("clean"),
        "timing_met": timing.get("timing_met"),
    }
    signoff_clean = all(vals[c] is True for c in _CRITERIA)
    partial = any(vals[c] is None for c in _CRITERIA)

    return {
        # --- join key: MUST match aggregate.py's row keys ---
        "arm": args.arm,
        "design": args.design,
        "seed": args.seed,
        "module": args.module or args.design,
        # --- verdict ---
        "signoff_clean": signoff_clean,
        "golden": vals["golden"],
        "lint": vals["lint"],
        "cdc": vals["cdc"],
        "timing_met": vals["timing_met"],
        "wns_setup_ns": timing.get("wns_setup_ns"),
        "wns_hold_ns": timing.get("wns_hold_ns"),
        "adjudication_partial": partial,
        # --- audit trail ---
        "workdir": str(workdir),
        "detail": {"golden": golden, "lint": lint, "cdc": cdc, "timing": timing},
    }


# --------------------------------------------------------------------------- #
# output (same .json/.csv shape family as aggregate.py; join key aligned)      #
# --------------------------------------------------------------------------- #
_CSV_COLUMNS = [
    "arm",
    "design",
    "seed",
    "module",
    "signoff_clean",
    "golden",
    "lint",
    "cdc",
    "timing_met",
    "wns_setup_ns",
    "wns_hold_ns",
    "adjudication_partial",
    "workdir",
]


def write_outputs(rows: list[dict], out_prefix: Path, append: bool) -> None:
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    jpath = out_prefix.with_suffix(".json")
    existing = []
    if append and jpath.exists():
        existing = json.loads(jpath.read_text()).get("runs", [])
    all_rows = existing + rows
    jpath.write_text(json.dumps({"runs": all_rows}, indent=2) + "\n")
    with out_prefix.with_suffix(".csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k) for k in _CSV_COLUMNS})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RTL -> signoff-clean adjudication (§1.3)")
    ap.add_argument("--arm", required=True, help="full | B1-lean | ... (join key)")
    ap.add_argument("--design", required=True, help="e.g. flash_attn (join key)")
    ap.add_argument("--seed", required=True, type=int, help="i-th repeat (join key)")
    ap.add_argument(
        "--module",
        default=None,
        help="join key; defaults to --design (matches aggregate.py "
        "when design==module, e.g. fa_core_fsa)",
    )
    ap.add_argument(
        "--rtl-sourcelist",
        default=None,
        help="PREFERRED: arm RTL-only sourcelist — synthesizable RTL, "
        "one path per line, no TB/UVM/+incdir (the wrapper's "
        "filelist.txt). Feeds both lint/cdc and synth.",
    )
    ap.add_argument(
        "--rtl",
        default=None,
        help="fallback: a VCS/DC manifest (filelist.f). Used only if "
        "--rtl-sourcelist is absent; the RTL list is derived from "
        "it (blank/#/-/+/$ dropped) with a warning — a TB .sv "
        "cannot be auto-excluded, so prefer --rtl-sourcelist.",
    )
    ap.add_argument(
        "--fixed",
        required=True,
        help="dir with pre-registered fixed bar: design.sdc, design.sgdc",
    )
    ap.add_argument("--top", required=True, help="top module name")
    ap.add_argument("--lib-db", default=None, help="std-cell .db (else $LIB_DB)")
    ap.add_argument(
        "--wrapper",
        default=str(_DEFAULT_WRAPPER),
        help="b1-wrapper dir (arm-neutral tool layer)",
    )
    ap.add_argument(
        "--golden-verdict",
        choices=["pass", "fail"],
        default=None,
        help="record the manually-run independent golden result (§1.3)",
    )
    ap.add_argument(
        "--golden-cmd",
        default=None,
        help="optional: external golden checker (exit 0 == pass)",
    )
    ap.add_argument("--workdir", default=None, help="sandbox dir (else auto)")
    ap.add_argument("--out", required=True, help="output prefix (.json/.csv)")
    ap.add_argument(
        "--append",
        action="store_true",
        help="append this row to an existing --out.json",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="build the sandbox, skip tool launches (wiring smoke)",
    )
    args = ap.parse_args(argv)

    row = adjudicate_run(args)
    write_outputs([row], Path(args.out), args.append)
    print(
        json.dumps(
            {
                "arm": row["arm"],
                "design": row["design"],
                "seed": row["seed"],
                "signoff_clean": row["signoff_clean"],
                "partial": row["adjudication_partial"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
