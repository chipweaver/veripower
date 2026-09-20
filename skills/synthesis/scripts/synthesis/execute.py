"""Calculate synthesis reports in a fresh attempt and publish complete deliverables."""

import shutil
import subprocess
from pathlib import Path

from synthesis import result


def run(workdir) -> int:
    workdir = Path(workdir).resolve()
    for name in ("result.json", "run.log"):
        (workdir / name).unlink(missing_ok=True)
    reports = workdir / "reports"
    if reports.is_symlink():
        reports.unlink()
    elif reports.exists():
        shutil.rmtree(reports)
    if not (workdir / "scripts/dc_run.tcl").is_file():
        raise FileNotFoundError(workdir / "scripts/dc_run.tcl")
    attempt = workdir / ".pending"
    if attempt.exists():
        shutil.rmtree(attempt)
    attempt.mkdir()
    for source in workdir.iterdir():
        if source.name in {
            ".pending",
            "dispatch.json",
            "evidence",
            "out",
            "reports",
            "work",
            "result.json",
            "run.log",
        }:
            continue
        target = attempt / source.name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    log = workdir / "run.log"
    print(f"[synthesis run] {log}", flush=True)
    with log.open("w") as stream:
        exit_code = subprocess.run(
            ["dc_shell", "-f", "scripts/dc_run.tcl"],
            cwd=attempt,
            stdout=stream,
            stderr=subprocess.STDOUT,
        ).returncode
    errors = any(
        line.startswith(("Error:", "ERROR:"))
        for line in log.read_text(errors="replace").splitlines()
    )
    if exit_code or errors:
        return exit_code if exit_code > 0 else 1
    if result.run(attempt / "reports", [])[0] or result.missing_netlist(attempt):
        return 1
    old_out = workdir / "out"
    if old_out.is_symlink():
        old_out.unlink()
    elif old_out.exists():
        shutil.rmtree(old_out)
    for name in ("out", "reports"):
        (attempt / name).replace(workdir / name)
    shutil.rmtree(attempt)
    return 0
