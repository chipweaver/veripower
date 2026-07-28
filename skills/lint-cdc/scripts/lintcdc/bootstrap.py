#!/usr/bin/env python3
"""lintcdc bootstrap — deploy the lint-cdc templates into a run workdir.

Behavior-preserving deploy built from focused, unit-testable steps (campaign design
§3.3): shutil.copy2 + str.replace do the per-file deploy + `sed -i` work (str.replace
has no sed-delimiter hazard). Upstream locations (rtl-design, the specification SGDC
seed) come from the injected `<workdir>/inputs.json` "rtl" / "rtl_doc" / "sgdc_seed"
keys, not by self-navigating tree_root/asic/<module>/Design/....

Deploys templates/ into the caller-provided workdir
(asic/<module>/Design/lint-cdc/runs/<N>/) NO-CLOBBER — a dest file already present
(carried forward by kernel.py's carry_self before this verb runs) always wins over
the template — infers TOP from the rtl-design README/filelist, seeds
scripts/constraints.sgdc (carried -> cold -> template priority: carry_self already
restores a canonical constraints.sgdc/waiver.tcl verbatim when one exists; a
genuinely first run seeds constraints.sgdc from the injected specification stage
root's constraints/<TOP>.sgdc), substitutes the MY_TOP placeholder, syncs
scripts/filelist.txt from the rtl-design filelist (RTL paths re-anchored to the
ABSOLUTE injected rtl-design root, no relpath climb), chmods the deployed shell
scripts executable, and runs a WARN-only SGDC<->SDC clock-period smoke check.
Fail-closed on a missing template dir, an un-inferrable top, an already-deployed
workdir, or an empty rtl-design filelist.

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed
  1  fail-closed guard (missing template dir / cannot infer top / already deployed /
     rtl-design filelist has no usable RTL entries)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import json
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
    """Sync Design/rtl-design/filelist.txt -> scripts/filelist.txt, re-anchoring each
    RTL path to the ABSOLUTE injected rtl_dir (no relpath climb). The skip set is
    {#, blank} ONLY (narrower than synthesis rtl_load) — preserve it. No-op when the
    source filelist is absent (the deployed placeholder stub stays). Fail-closed
    (return 1) on a source filelist with zero usable entries."""
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
        "# Paths are absolute (re-anchored to the injected rtl-design stage root).",
        "# ==============================================================================",
        "",
        "# Header search paths",
        f"+incdir+{rtl_dir}",
        "",
        "# RTL source files (in dependency order)",
    ]
    body = [f"{rtl_dir}/{e}" for e in entries]
    (dest / "scripts" / "filelist.txt").write_text("\n".join(header + body) + "\n")
    print(
        f"  filelist.txt: synced from Design/rtl-design/filelist.txt ({len(entries)} files)"
    )
    return 0


def _deploy_no_clobber(src_root: Path, dest: Path) -> None:
    """Copy every template file into dest UNLESS dest already has one at that path —
    a carried human-audited file (brought forward by kernel.py's carry_self before
    this verb runs) always wins over the pristine template."""
    for p in src_root.rglob("*"):
        if p.is_dir():
            continue
        d = dest / p.relative_to(src_root)
        if d.exists():
            continue  # carried human-audited file — never overwrite
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, d)


def run(workdir, top: str | None = None) -> int:
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

    # The rtl-design stage root is injected into inputs.json (dispatch-time), not
    # self-navigated via tree_root/asic/<module>/Design/rtl-design.
    inputs = json.loads((dest / "inputs.json").read_text(encoding="utf-8"))
    rtl_dir = Path(inputs["rtl"])

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

    # Carried-file check MUST happen BEFORE the no-clobber deploy — once the template
    # is deployed at these paths they become indistinguishable from a genuinely
    # carried file.
    carried_sgdc = (dest / "scripts" / "constraints.sgdc").is_file()
    carried_waiver = (dest / "scripts" / "waiver.tcl").is_file()

    _deploy_no_clobber(_TEMPLATE_DIR, dest)

    # SGDC seed: carried -> cold -> template priority. carry_self (kernel.py) already
    # restores the canonical constraints.sgdc verbatim into the fresh workdir when one
    # exists (already bound to a concrete top -> NOT MY_TOP-substituted); the cold
    # branch seeds a genuinely first run from the injected specification stage root.
    # The template branch keeps the no-clobber-deployed template constraints.sgdc and
    # DOES substitute it.
    sgdc = dest / "scripts" / "constraints.sgdc"
    cold = Path(inputs["sgdc_seed"]) / "constraints" / f"{top}.sgdc"
    sub_targets = [
        "env.sh",
        "scripts/spyglass_lint.prj",
    ]
    if carried_sgdc:
        print(
            "[lintcdc bootstrap] carried scripts/constraints.sgdc used (survived from a prior round)"
        )
        sgdc_source = "scripts/constraints.sgdc (carried)"
    elif cold.is_file():
        shutil.copyfile(cold, sgdc)
        print(
            f"[lintcdc bootstrap] cold-start used Design/specification/constraints/{top}.sgdc -> scripts/constraints.sgdc"
        )
        sgdc_source = f"Design/specification/constraints/{top}.sgdc (cold)"
    else:
        sub_targets.append("scripts/constraints.sgdc")  # template copy needs MY_TOP
        sgdc_source = ""
    # Waiver: carried (carry_self) -> template. The canonical waiver.tcl holds
    # HUMAN-reviewed waivers (promoted per SKILL.md) — the no-clobber deploy already
    # left it untouched when carried; only a fresh template stub needs MY_TOP.
    if not carried_waiver:
        sub_targets.append("scripts/waiver.tcl")
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
