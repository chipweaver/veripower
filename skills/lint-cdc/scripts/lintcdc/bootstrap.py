#!/usr/bin/env python3
"""lintcdc bootstrap — deploy the lint-cdc templates into a run workdir.

Behavior-preserving deploy built from focused, unit-testable steps (campaign design
§3.3): shutil.copytree + str.replace do the `cp -a` + `sed -i` work (str.replace has
no sed-delimiter hazard).

Deploys templates/ into the caller-provided workdir
(asic/<module>/Design/lint-cdc/runs/<N>/), infers TOP from the rtl-design
README/filelist, seeds scripts/constraints.sgdc (warm -> cold -> template priority),
substitutes the MY_TOP placeholder, syncs scripts/filelist.txt from the rtl-design
filelist (RTL paths rebased to ../../../rtl-design/...), chmods the deployed shell
scripts executable, and runs a WARN-only SGDC<->SDC clock-period smoke check.
Fail-closed on a missing template dir, a missing design tree (rtl-design dir absent
under the CWD), an un-inferrable top, an already-deployed workdir, or an empty
rtl-design filelist.

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed
  1  fail-closed guard (missing template dir / missing design tree / cannot infer top
     / already deployed / rtl-design filelist has no usable RTL entries)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# This file: skills/lint-cdc/scripts/lintcdc/bootstrap.py
#   parents[2] = skills/lint-cdc   (-> templates/, ships with the skill)
# The design tree (asic/<module>/...) is anchored on the CWD, NOT on where this code
# lives — matching kernel.py and the stage-subagent contract ("workdir is relative to
# the working tree root containing asic/").
_HERE = Path(__file__).resolve()
_TEMPLATE_DIR = _HERE.parents[2] / "templates"

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SGDC_CLK = re.compile(r"^\s*clock\s")
_SDC_CLK = re.compile(r"^\s*create_clock\s")
_PERIOD = re.compile(r"-period\s+(\d+(?:\.\d+)?)")


def _err(msg: str) -> None:
    print(f"[lintcdc bootstrap] {msg}", file=sys.stderr)


def infer_top_from_readme(rtl_dir: Path) -> str | None:
    """First non-table line naming a top module -> first identifier after ':'/'：'.

    Matches a top-module line: case-insensitive 'top' / 'top module' preceded by
    start / '*' / '#' / whitespace, excluding markdown table rows (first match wins);
    the capture charset allows a leading digit but the identifier validation then
    rejects it. A ':' or '：' is REQUIRED — a colon-less line is not matched. The
    producer always emits the cross-stage contract form `**Top module**: <top>`, so
    requiring the colon matches the actual contract and the colon-less case has no
    real input.
    """
    f = rtl_dir / "README.md"
    if not f.is_file():
        return None
    line_re = re.compile(r"(^|[*#\s])(top|top\s+module)", re.I)
    extract_re = re.compile(r"^[^:：]*[:：]\s*([A-Za-z0-9_]+)")
    for raw in f.read_text(errors="replace").splitlines():
        line = raw.replace("\r", "")
        if re.match(r"^\s*\|", line):  # skip markdown table rows
            continue
        if not line_re.search(line):
            continue
        m = extract_re.match(line)
        if not m:
            return None
        top = m.group(1)
        return top if _IDENT_RE.match(top) else None
    return None


def infer_top_from_filelist(rtl_dir: Path) -> str | None:
    """First true RTL path entry's basename (.v/.sv/.vh stripped) -> top, when an
    identifier. Skips comments (#), blanks, and +/- directives (the inference skip
    set is {#, blank, +/-} — NO '//' skip). Extensions are stripped sequentially (a
    name ending '.sv.v' loses both).
    """
    f = rtl_dir / "filelist.txt"
    if not f.is_file():
        return None
    for raw in f.read_text(errors="replace").splitlines():
        line = raw.replace("\r", "")
        if re.match(r"^\s*#", line) or not line.strip() or re.match(r"^\s*[+\-]", line):
            continue
        base = os.path.basename(line)
        for ext in (".v", ".sv", ".vh"):
            if base.endswith(ext):
                base = base[: -len(ext)]
        return base if _IDENT_RE.match(base) else None
    return None


def _sub(path: Path, placeholder: str, value: str) -> None:
    """In-place placeholder substitution (str.replace — no sed-delimiter hazard)."""
    path.write_text(path.read_text().replace(placeholder, value))


def _sync_filelist(dest: Path, rtl_dir: Path) -> int:
    """Sync Design/rtl-design/filelist.txt -> scripts/filelist.txt, rebasing each RTL
    path to ../../../rtl-design/<entry> (fixed prefix relative to scripts/, NOT relpath).
    The skip set is {#, blank} ONLY (narrower than synthesis rtl_load) — preserve it.
    No-op when the source filelist is absent (the MY_TOP-substituted template stays).
    Fail-closed (return 1) on a source filelist with zero usable entries."""
    src = rtl_dir / "filelist.txt"
    if not src.is_file():
        return 0
    entries = []
    for raw in src.read_text(errors="replace").splitlines():
        line = raw.replace("\r", "")
        if re.match(r"^\s*#", line) or not line.strip():
            continue
        entries.append(line)
    if not entries:
        _err(f"{src} has no usable RTL entries (only comments / blank lines)")
        _err(
            "  Populate Design/rtl-design/filelist.txt with .v / .sv paths in "
            "dependency order."
        )
        return 1
    header = [
        "# ==============================================================================",
        "# filelist.txt — RTL file list (SpyGlass sourcelist format).",
        "# Generated by the lint-cdc bootstrap verb from Design/rtl-design/filelist.txt.",
        "# Paths are relative to Design/lint-cdc/runs/<N>/ (the deployment location).",
        "# ==============================================================================",
        "",
        "# Header search paths",
        "+incdir+../../../rtl-design",
        "",
        "# RTL source files (in dependency order)",
    ]
    body = [f"../../../rtl-design/{e}" for e in entries]
    (dest / "scripts" / "filelist.txt").write_text("\n".join(header + body) + "\n")
    print(
        f"  filelist.txt: synced from Design/rtl-design/filelist.txt ({len(entries)} files)"
    )
    return 0


def _first_period(path: Path, anchor: re.Pattern) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(errors="replace").splitlines():
        if anchor.match(line):
            m = _PERIOD.search(line)
            if m:
                return m.group(1)
    return None


def _check_period(sgdc: Path, sdc: Path) -> None:
    """WARN-only smoke check: first clock period in spec <TOP>.sgdc vs <TOP>.sdc.
    Mismatch prints a WARNING to stderr and NEVER fails; either file missing / either
    period unparseable -> silent no-op (consistency is a specification rework)."""
    sg = _first_period(sgdc, _SGDC_CLK)
    sd = _first_period(sdc, _SDC_CLK)
    if sg is None or sd is None or sg == sd:
        return
    _err(
        "WARNING: SGDC and SDC clock periods disagree; update per design.md §1.6 before re-running."
    )
    _err(f"  {sgdc.name}  clock -period       = {sg} ns")
    _err(f"  {sdc.name}   create_clock -period = {sd} ns")


def run(module: str, workdir, top: str | None = None) -> int:
    if not _TEMPLATE_DIR.is_dir():
        _err(f"missing template directory: {_TEMPLATE_DIR}")
        return 1

    # The design tree is the CWD (kernel.py + stage-subagent contract). Resolve a
    # relative workdir against it + drop trailing slash.
    tree_root = Path.cwd()
    dest = Path(workdir)
    if not dest.is_absolute():
        dest = tree_root / dest
    dest = Path(str(dest).rstrip("/"))

    rtl_dir = tree_root / "asic" / module / "Design" / "rtl-design"
    if not rtl_dir.is_dir():
        _err(f"design tree not found: {rtl_dir}")
        _err(
            "  Run from the working tree root (the directory containing asic/); "
            "upstream rtl-design must exist."
        )
        return 1

    # Infer TOP (README first, then filelist) BEFORE mkdir/guard (shell order).
    if not top:
        top = infer_top_from_readme(rtl_dir)
    if not top:
        top = infer_top_from_filelist(rtl_dir)
    if not top:
        _err("cannot infer top-module name; pass --top <name>")
        _err("  Add a 'Top: <name>' line to Design/rtl-design/README.md, or")
        _err("  ensure Design/rtl-design/filelist.txt begins with an RTL path.")
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    # A caller may pre-create the workdir with hint files (directive.md
    # etc.); only treat it as already-deployed when Makefile is present.
    if (dest / "Makefile").is_file():
        _err(f"already deployed (detected {dest / 'Makefile'})")
        _err(
            f"  To redeploy, back up and remove {dest}/{{Makefile,env.sh,scripts/}} first."
        )
        return 1

    shutil.copytree(_TEMPLATE_DIR, dest, dirs_exist_ok=True)

    # SGDC seed: warm -> cold -> template priority. warm/cold are already bound to a
    # concrete top -> copied verbatim, NOT MY_TOP-substituted. The template branch keeps
    # the copytree'd template constraints.sgdc and DOES substitute it.
    warm = (
        tree_root
        / "asic"
        / module
        / "Design"
        / "lint-cdc"
        / "scripts"
        / "constraints.sgdc"
    )
    cold = (
        tree_root
        / "asic"
        / module
        / "Design"
        / "specification"
        / "constraints"
        / f"{top}.sgdc"
    )
    sub_targets = [
        "env.sh",
        "scripts/spyglass_lint.prj",
        "scripts/filelist.txt",
        "scripts/waiver.tcl",
    ]
    if warm.is_file():
        shutil.copyfile(warm, dest / "scripts" / "constraints.sgdc")
        print(
            "[lintcdc bootstrap] warm-start used Design/lint-cdc/scripts/constraints.sgdc -> scripts/constraints.sgdc"
        )
        sgdc_source = "Design/lint-cdc/scripts/constraints.sgdc (warm)"
    elif cold.is_file():
        shutil.copyfile(cold, dest / "scripts" / "constraints.sgdc")
        print(
            f"[lintcdc bootstrap] cold-start used Design/specification/constraints/{top}.sgdc -> scripts/constraints.sgdc"
        )
        sgdc_source = f"Design/specification/constraints/{top}.sgdc (cold)"
    else:
        sub_targets.append("scripts/constraints.sgdc")  # template copy needs MY_TOP
        sgdc_source = ""
    for rel in sub_targets:
        _sub(dest / rel, "MY_TOP", top)

    # Make the deployed shell scripts executable (best-effort).
    for sh in (dest / "scripts").glob("*.sh"):
        try:
            sh.chmod(sh.stat().st_mode | 0o111)
        except OSError:
            pass

    rc = _sync_filelist(dest, rtl_dir)
    if rc != 0:
        return rc

    spec_con = tree_root / "asic" / module / "Design" / "specification" / "constraints"
    _check_period(spec_con / f"{top}.sgdc", spec_con / f"{top}.sdc")

    print(f"[lintcdc bootstrap] deployed {dest}")
    print(f"  TOP={top}")
    if sgdc_source:
        print(
            f"  clock/reset constraints: synced from {sgdc_source}; add abstract_port associations as needed."
        )
    else:
        print(
            "  clock/reset constraints: edit scripts/constraints.sgdc (clock / reset / abstract_port)."
        )
    print(
        f'  Next: cd "{dest}" && make all   (requires SpyGlass; -shell -tcl mode does not need Xvfb)'
    )
    return 0
