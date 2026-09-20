"""Analyze timing without exposing an old or incomplete report as current."""

import shutil
import subprocess
from pathlib import Path

from timing import result


def run(workdir) -> int:
    workdir = Path(workdir).resolve()
    for name in ("result.json", "run.log", "timing-report.txt"):
        (workdir / name).unlink(missing_ok=True)
    reports = workdir / "reports"
    if reports.is_symlink():
        reports.unlink()
    elif reports.exists():
        shutil.rmtree(reports)
    if not (workdir / "run_sta.tcl").is_file():
        raise FileNotFoundError(workdir / "run_sta.tcl")
    attempt = workdir / ".pending"
    if attempt.exists():
        shutil.rmtree(attempt)
    attempt.mkdir()
    for source in workdir.iterdir():
        if source.name in {
            ".pending",
            "dispatch.json",
            "evidence",
            "timing-report.txt",
            "reports",
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
    print(f"[timing run] {log}", flush=True)
    with log.open("w") as stream:
        exit_code = subprocess.run(
            ["pt_shell", "-f", "run_sta.tcl"],
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
    report = attempt / "timing-report.txt"
    if result.run(report)[0]:
        return 1
    if (attempt / "reports").exists():
        (attempt / "reports").replace(reports)
    report.replace(workdir / "timing-report.txt")
    shutil.rmtree(attempt)
    return 0
