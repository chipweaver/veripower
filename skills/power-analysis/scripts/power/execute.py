"""Run authored experiments or independently calculate their power."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from power.scenarios import load


def run(workdir, mode):
    wd = Path(workdir).resolve()
    (wd / "result.json").unlink(missing_ok=True)
    inputs = json.loads((wd / "dispatch.json").read_text())["inputs"]
    ids = load(inputs["plan"])
    # Clear the whole selected set before launching anything, including attempts interrupted
    # before reaching later scenarios. No old report may qualify a new partial execution.
    for sid in ids:
        reports = wd / "reports_ptpx" / sid
        if reports.exists():
            shutil.rmtree(reports)
        if mode in ("compile", "simulate"):
            for suffix in ("saif", "status"):
                (wd / "saif" / f"{sid}.{suffix}").unlink(missing_ok=True)
    if mode == "compile":
        with (wd / "gls-compile-log.txt").open("w") as output:
            rc = subprocess.run(
                ["bash", "experiment/compile.sh"],
                cwd=wd,
                stdout=output,
                stderr=subprocess.STDOUT,
            ).returncode
        if rc:
            return rc
        return subprocess.run(
            ["bash", "scripts/check_sdf_annotated.sh", "gls-compile-log.txt"], cwd=wd
        ).returncode

    failed = []
    for sid in ids:
        saif = wd / "saif" / f"{sid}.saif"
        status = saif.with_suffix(".status")
        reports = wd / "reports_ptpx" / sid
        env = os.environ.copy()
        if mode == "simulate":
            saif.parent.mkdir(exist_ok=True)
            command = ["bash", "experiment/run.sh", sid, str(saif), str(status)]
            log = saif.with_suffix(".run.log")
        else:
            if (
                not saif.is_file()
                or not saif.stat().st_size
                or not status.is_file()
                or status.read_text().strip() != "PASS"
            ):
                print(
                    f"[power calculate] {sid}: missing activity or successful experiment completion",
                    flush=True,
                )
                failed.append(sid)
                continue
            pending = wd / ".pending" / sid
            if pending.exists():
                shutil.rmtree(pending)
            pending.mkdir(parents=True)
            env.update(SCENARIO=sid, SAIF_FILE=str(saif), REPORTS_DIR=str(pending))
            command = ["pt_shell", "-f", "scripts/ptpx.tcl"]
            log = pending / "ptpx.log"
        print(f"[power {mode}] {sid}: {log}", flush=True)
        with log.open("w") as output:
            rc = subprocess.run(
                command, cwd=wd, env=env, stdout=output, stderr=subprocess.STDOUT
            ).returncode
        if mode == "simulate":
            complete = (
                saif.is_file()
                and saif.stat().st_size > 0
                and status.is_file()
                and status.read_text().strip() == "PASS"
            )
            if rc or not complete:
                status.write_text("FAIL\n")
                failed.append(sid)
        elif (
            rc
            or any(
                line.startswith(("Error:", "ERROR:"))
                for line in log.read_text(errors="replace").splitlines()
            )
            or not (pending / "power_flat.rpt").is_file()
        ):
            failed.append(sid)
        else:
            reports.parent.mkdir(exist_ok=True)
            pending.replace(
                reports
            )  # Only a completed tool process publishes gradeable reports.
    if failed:
        print(f"[power {mode}] failed: {', '.join(failed)}", flush=True)
    return int(bool(failed))
