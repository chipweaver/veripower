"""Analyze timing without exposing an old or incomplete report as current."""

import shutil
import subprocess
from pathlib import Path

from timing import result


def run(workdir) -> int:
    wd = Path(workdir).resolve()
    for name in ("result.json", "run.log", "timing-report.txt"):
        (wd / name).unlink(missing_ok=True)
    reports = wd / "reports"
    if reports.is_symlink():
        reports.unlink()
    elif reports.exists():
        shutil.rmtree(reports)
    if not (wd / "run_sta.tcl").is_file():
        raise FileNotFoundError(wd / "run_sta.tcl")
    attempt = wd / ".pending"
    if attempt.exists():
        shutil.rmtree(attempt)
    attempt.mkdir()
    for source in wd.iterdir():
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
    log = wd / "run.log"
    print(f"[timing run] {log}", flush=True)
    with log.open("w") as stream:
        rc = subprocess.run(
            ["pt_shell", "-f", "run_sta.tcl"],
            cwd=attempt,
            stdout=stream,
            stderr=subprocess.STDOUT,
        ).returncode
    errors = any(
        line.startswith(("Error:", "ERROR:"))
        for line in log.read_text(errors="replace").splitlines()
    )
    if rc or errors:
        return rc if rc > 0 else 1
    report = attempt / "timing-report.txt"
    if result.run(report)[0]:
        return 1
    if (attempt / "reports").exists():
        (attempt / "reports").replace(reports)
    report.replace(wd / "timing-report.txt")
    shutil.rmtree(attempt)
    return 0
