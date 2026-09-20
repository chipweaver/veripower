#!/usr/bin/env python3
"""Refresh generated inputs and install missing tool configuration and driver files."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

# This file: skills/synthesis/scripts/synthesis/bootstrap.py
#   parents[2] = skills/synthesis   (-> templates/, ships with the skill)
# The kernel hands this verb an ABSOLUTE workdir, so nothing here depends on where it
# was launched from. A relative --workdir is still resolved against the CWD, for a
# human running the verb by hand from inside the module.
SCRIPT_PATH = Path(__file__).resolve()
TEMPLATE_DIR = SCRIPT_PATH.parents[2] / "templates"

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def report_error(msg: str) -> None:
    print(f"[synthesis bootstrap] {msg}", file=sys.stderr)


def top_from_manifest(manifest_dir: Path) -> str | None:
    """TOP from the injected manifest's `module` — the name the specification stage
    authored, which every other copy in the tree derives from."""
    f = Path(manifest_dir) / "manifest.json"
    if not f.is_file():
        return None
    try:
        top = json.loads(f.read_text(encoding="utf-8")).get("module")
    except json.JSONDecodeError:
        return None
    return top if isinstance(top, str) and IDENT_RE.match(top) else None


def load_rtl_files(rtl_dir: Path) -> dict | None:
    """rtl-files.json from the injected rtl-design stage root.

    Not validated here: rtl-design schema-validates it when it writes it, and a stage does
    not reach into another skill's references/ (skills stay decoupled).
    """
    try:
        return json.loads((rtl_dir / "rtl-files.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def quote_tcl_word(value: str) -> str:
    """Quote one literal Tcl argument, including substitution characters."""
    return json.dumps(value, ensure_ascii=False).replace("$", "\\$").replace("[", "\\[")


def render_rtl_load_tcl(rtl_dir: Path) -> str | None:
    """Render RTL in the integrated compilation order."""
    rtl_files = load_rtl_files(rtl_dir)
    if rtl_files is None:
        report_error(f"missing or unreadable {rtl_dir / 'rtl-files.json'}")
        report_error(
            "  rtl-design writes it from its children's reports; re-run that stage."
        )
        return None
    rtl_entries = rtl_files["files"]
    incdirs = [f"{rtl_dir}/{d}" for d in rtl_files.get("incdirs", [])]
    if not rtl_entries:
        report_error(f"{rtl_dir / 'rtl-files.json'} lists no RTL files")
        report_error(
            "  rtl-design writes it from its children's reports; re-run that stage."
        )
        return None
    body = [
        "# Generated from rtl-files.json; bootstrap replaces this file.",
        "# analyze returns 0 on failure without raising a Tcl error.",
        "proc analyze_source {f} {",
        "    if {![analyze -format sverilog -define SYNTHESIS [list $f]]} {",
        '        puts stderr "ERROR: analyze failed: $f"',
        "        exit 1",
        "    }",
        "}",
    ]
    if incdirs:
        body.append(
            "set_app_var search_path [concat [get_app_var search_path] "
            f"[list {' '.join(quote_tcl_word(d) for d in incdirs)}]]"
        )
    for entry in rtl_entries:
        body.append(f"analyze_source {quote_tcl_word(f'{rtl_dir}/{entry}')}")
    return "\n".join(body) + "\n"


LOCAL_SDC_STUB = """# Design-declared exceptions and justified local timing/IO settings.
# Loaded after constraints.sdc. Keep the reasoning with the commands.
"""


def deploy_sdc(dest: Path, seed: Path) -> None:
    """Refresh the specification SDC and preserve the stage's local constraints.

    dc_run.tcl reads both files on each invocation, seed first.
    """
    local = dest / "constraints.local.sdc"
    if not local.is_file():
        local.write_text(LOCAL_SDC_STUB)
    shutil.copyfile(seed, dest / "constraints.sdc")
    print(f"[synthesis bootstrap] constraints.sdc: copied from constraints/{seed.name}")


def run(workdir, top: str | None = None) -> int:
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if not TEMPLATE_DIR.is_dir():
        report_error(f"missing template directory: {TEMPLATE_DIR}")
        return 1

    # The design tree is the CWD (kernel.py + stage-subagent contract). Resolve a
    # relative workdir against it + drop trailing slash.
    tree_root = Path.cwd()
    dest = Path(workdir)
    if not dest.is_absolute():
        dest = tree_root / dest
    dest = Path(str(dest).rstrip("/"))  # consistent path resolution

    inputs = json.loads((dest / "dispatch.json").read_text(encoding="utf-8"))["inputs"]
    rtl_dir = Path(inputs["rtl"])

    if not top:
        top = top_from_manifest(inputs["manifest"])
    if not top:
        report_error("cannot read top-module name; pass --top <name>")
        report_error("  Design/specification/manifest.json must carry a 'module' name.")
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    # Validate source inputs before preparing the tool files.
    user_sdc = Path(inputs["sdc"]) / "constraints" / f"{top}.sdc"
    if not user_sdc.is_file():
        report_error(f"SDC source of truth not found: {user_sdc}")
        report_error(
            "  specification's derive-constraints writes constraints/<TOP>.sdc; check that "
            "it ran and that --top matches manifest.module."
        )
        return 1

    rtl_load_tcl = render_rtl_load_tcl(rtl_dir)
    if rtl_load_tcl is None:
        return 1

    for source in TEMPLATE_DIR.rglob("*"):
        target = dest / source.relative_to(TEMPLATE_DIR)
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                source.read_text().replace("MY_RTL_DIR", quote_tcl_word(str(rtl_dir)))
            )
            shutil.copymode(source, target)

    deploy_sdc(dest, user_sdc)

    (dest / "scripts" / "rtl_load.tcl").write_text(rtl_load_tcl)

    config = dest / "config.tcl"
    if not config.exists():
        settings = {
            "TOP": top,
            "LIB_DB": os.environ.get("LIB_DB"),
            "WIRE_LOAD_MODEL": os.environ.get("WIRE_LOAD_MODEL"),
        }
        lines = [
            "# Tool configuration; supply the task's libraries and calculation settings."
        ]
        for key, value in settings.items():
            if value:
                lines.append(f"set {key} {quote_tcl_word(value)}")
        config.write_text("\n".join(lines) + "\n")

    print(f"\n[synthesis bootstrap] deployed {dest}")
    print(f"  TOP={top}")
    print(f"  RTL_DIR={rtl_dir}")
    return 0
