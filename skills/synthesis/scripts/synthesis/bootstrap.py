#!/usr/bin/env python3
"""synthesis bootstrap — deploy the synthesis templates into a run workdir.

Behavior-preserving deploy built from focused, unit-testable steps (campaign design
§3.3): shutil.copytree + str.replace do the `cp -a` + `sed -i` work (str.replace has
no sed-delimiter hazard on the '..'-containing RTL relpath); os.path.relpath computes
the RTL relpath inline.

Deploys templates/ into the caller-provided workdir
(asic/<module>/Design/synthesis/runs/<N>/), substitutes the MY_TOP / MY_RTL_DIR
placeholders, regenerates scripts/rtl_load.tcl from the rtl-design filelist, and
writes scripts/config.tcl. Fail-closed on a missing/empty filelist or an
un-inferrable top. Idempotency guard: aborts when the workdir is already deployed.

Exit codes (returned as int; __main__ does sys.exit):
  0  deployed
  1  fail-closed guard (cannot infer top / already deployed / missing or empty
     filelist / missing template dir)
  (2 = usage is owned by argparse in __main__.py)
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# This file: skills/synthesis/scripts/synthesis/bootstrap.py
#   parents[2] = skills/synthesis   (-> templates/, ships with the skill)
# The design tree (asic/<module>/...) is anchored on the CWD, NOT on where this code
# lives — matching state.py and the stage-subagent contract ("workdir is relative to
# the working tree root containing asic/").
_HERE = Path(__file__).resolve()
_TEMPLATE_DIR = _HERE.parents[2] / "templates"

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _err(msg: str) -> None:
    print(f"[synthesis bootstrap] {msg}", file=sys.stderr)


def infer_top_from_readme(rtl_dir: Path) -> str | None:
    """First non-table line naming a top module -> first identifier after ':'/'：'.

    Matches a top-module line: case-insensitive 'top' / 'top module' preceded by
    start / '*' / '#' / whitespace, excluding markdown table rows (first match wins);
    the capture charset allows a leading digit but the identifier validation then
    rejects it. A ':' or '：' is REQUIRED — a colon-less line is not matched. The
    producer always emits the cross-stage contract form `**Top module**: <top>`
    (locked by test_rtl_assemble.py), so requiring the colon matches the actual
    contract and the colon-less case has no real input.
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


def _is_rtl_entry(line: str) -> bool:
    """True for a real RTL path line in filelist.txt — not a comment (# or //),
    blank, or +/- directive. (rtl_load skip set is {#, //, blank, +/-}.)"""
    if re.match(r"^\s*#", line):
        return False
    if re.match(r"^\s*//", line):
        return False
    if not line.strip():
        return False
    if re.match(r"^\s*[+\-]", line):
        return False
    return True


def _sub(path: Path, placeholder: str, value: str) -> None:
    """In-place placeholder substitution (str.replace — no sed-delimiter hazard)."""
    path.write_text(path.read_text().replace(placeholder, value))


def _write_rtl_load_tcl(dest: Path, rtl_dir: Path, rtl_rel_dir: str) -> int:
    """Regenerate scripts/rtl_load.tcl from filelist.txt (overwrites the template
    placeholder copied by copytree). Fail-closed (return 1) on missing/empty filelist."""
    out = dest / "scripts" / "rtl_load.tcl"
    fl = rtl_dir / "filelist.txt"
    if not fl.is_file():
        _err(f"missing {fl}")
        _err(
            "  Populate Design/rtl-design/filelist.txt with .v / .sv paths in "
            "dependency order."
        )
        return 1
    lines = fl.read_text(errors="replace").splitlines()
    rtl_entries = [ln.replace("\r", "") for ln in lines if _is_rtl_entry(ln)]
    if not rtl_entries:
        _err(f"{fl} has no usable RTL entries (only comments / directives)")
        _err(
            "  Populate Design/rtl-design/filelist.txt with .v / .sv paths in "
            "dependency order."
        )
        return 1
    incdirs: list[str] = []
    for raw in lines:
        m = re.match(r"^\s*\+incdir\+(.+)$", raw.replace("\r", ""))
        if m:
            incdirs.append(f"{rtl_rel_dir}/{m.group(1)}")
    body = [
        "# Generated by synthesis bootstrap from Design/rtl-design/filelist.txt — hand-edit OK"
    ]
    if incdirs:
        body.append(
            "set_app_var search_path [concat [get_app_var search_path] "
            f"[list {' '.join(incdirs)}]]"
        )
    for entry in rtl_entries:
        body.append(
            f"analyze -format sverilog -define SYNTHESIS [list {rtl_rel_dir}/{entry}]"
        )
    out.write_text("\n".join(body) + "\n")
    return 0


def _write_config_tcl(dest: Path, top: str) -> None:
    """Generate scripts/config.tcl (dc_shell does not inherit shell env vars).
    LIB_DB falls back to the FILL_IN placeholder when unset/empty (shell `${LIB_DB:-}`)."""
    lib_db = os.environ.get("LIB_DB") or "FILL_IN_LIB_DB_PATH"
    (dest / "scripts" / "config.tcl").write_text(
        "# Auto-generated by synthesis bootstrap — dc_shell / pt_shell configuration.\n"
        "# dc_shell does not inherit shell env vars; this file is the sole entry point\n"
        "# for TOP and LIB_DB. Editing LIB_DB here does not require a re-bootstrap.\n"
        f'set ::env(TOP)    "{top}"\n'
        f'set ::env(LIB_DB) "{lib_db}"\n'
    )
    if lib_db == "FILL_IN_LIB_DB_PATH":
        print(
            "[synthesis bootstrap] wrote scripts/config.tcl "
            "(fill in LIB_DB path before make synthesis)"
        )
    else:
        print(f"[synthesis bootstrap] wrote scripts/config.tcl (LIB_DB={lib_db})")


def run(module: str, workdir, top: str | None = None) -> int:
    if not _TEMPLATE_DIR.is_dir():
        _err(f"missing template directory: {_TEMPLATE_DIR}")
        return 1

    # The design tree is the CWD (state.py + stage-subagent contract). Resolve a
    # relative workdir against it + drop trailing slash.
    tree_root = Path.cwd()
    dest = Path(workdir)
    if not dest.is_absolute():
        dest = tree_root / dest
    dest = Path(str(dest).rstrip("/"))  # consistent relpath math

    rtl_dir = tree_root / "asic" / module / "Design" / "rtl-design"
    rtl_rel_dir = os.path.relpath(
        rtl_dir, dest
    )  # may contain '..' — str.replace handles it

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
    # A caller may pre-create the workdir with hint files (orchestrator-context.md
    # etc.); only treat it as already-deployed when Makefile is present.
    if (dest / "Makefile").is_file():
        _err(f"already deployed (detected {dest / 'Makefile'})")
        _err(
            f"  To redeploy, back up and remove {dest}/"
            "{Makefile,constraints.sdc,scripts/} first."
        )
        return 1

    shutil.copytree(_TEMPLATE_DIR, dest, dirs_exist_ok=True)

    # SDC source-of-truth: reuse the spec-stage SDC verbatim when present (already
    # bound to this top — no MY_TOP sub). env.sh is substituted in both branches.
    env_sh = dest / "env.sh"
    user_sdc = (
        tree_root
        / "asic"
        / module
        / "Design"
        / "specification"
        / "constraints"
        / f"{top}.sdc"
    )
    if user_sdc.is_file():
        shutil.copyfile(user_sdc, dest / "constraints.sdc")
        print(
            f"[synthesis bootstrap] using "
            f"Design/specification/constraints/{top}.sdc -> constraints.sdc"
        )
        _sub(env_sh, "MY_TOP", top)
    else:
        _sub(env_sh, "MY_TOP", top)
        _sub(dest / "constraints.sdc", "MY_TOP", top)
        print(
            "[synthesis bootstrap] no spec SDC; deployed PLACEHOLDER constraints.sdc "
            "(clk=10ns, ports clk/rst_n) — fill it per design.md §1.4 in Step 4."
        )

    _sub(dest / "scripts" / "dc_run.tcl", "MY_RTL_DIR", rtl_rel_dir)

    rc = _write_rtl_load_tcl(dest, rtl_dir, rtl_rel_dir)
    if rc != 0:
        return rc

    _write_config_tcl(dest, top)

    print(f"\n[synthesis bootstrap] deployed {dest}")
    print(f"  TOP={top}")
    print(f"  RTL_REL_DIR={rtl_rel_dir}")
    return 0
