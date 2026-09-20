"""Run authored experiments or independently calculate their power."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from power.scenarios import load


def run(workdir, mode):
    workdir = Path(workdir).resolve()
    (workdir / "result.json").unlink(missing_ok=True)
    inputs = json.loads((workdir / "dispatch.json").read_text())["inputs"]
    scenario_ids = load(inputs["plan"])
    # Clear the whole selected set before launching anything, including attempts interrupted
    # before reaching later scenarios. No old report may qualify a new partial execution.
    for scenario_id in scenario_ids:
        reports = workdir / "reports_ptpx" / scenario_id
        if reports.exists():
            shutil.rmtree(reports)
        if mode in ("compile", "simulate"):
            for suffix in ("saif", "status"):
                (workdir / "saif" / f"{scenario_id}.{suffix}").unlink(missing_ok=True)
    if mode == "compile":
        with (workdir / "gls-compile-log.txt").open("w") as output:
            exit_code = subprocess.run(
                ["bash", "experiment/compile.sh"],
                cwd=workdir,
                stdout=output,
                stderr=subprocess.STDOUT,
            ).returncode
        if exit_code:
            return exit_code
        return subprocess.run(
            ["bash", "scripts/check_sdf_annotated.sh", "gls-compile-log.txt"],
            cwd=workdir,
        ).returncode

    failed_scenarios = []
    for scenario_id in scenario_ids:
        saif_path = workdir / "saif" / f"{scenario_id}.saif"
        status_path = saif_path.with_suffix(".status")
        reports = workdir / "reports_ptpx" / scenario_id
        tool_environment = os.environ.copy()
        if mode == "simulate":
            saif_path.parent.mkdir(exist_ok=True)
            command = [
                "bash",
                "experiment/run.sh",
                scenario_id,
                str(saif_path),
                str(status_path),
            ]
            log = saif_path.with_suffix(".run.log")
        else:
            if (
                not saif_path.is_file()
                or not saif_path.stat().st_size
                or not status_path.is_file()
                or status_path.read_text().strip() != "PASS"
            ):
                print(
                    f"[power calculate] {scenario_id}: missing activity or successful experiment completion",
                    flush=True,
                )
                failed_scenarios.append(scenario_id)
                continue
            pending = workdir / ".pending" / scenario_id
            if pending.exists():
                shutil.rmtree(pending)
            pending.mkdir(parents=True)
            tool_environment.update(
                SCENARIO=scenario_id, SAIF_FILE=str(saif_path), REPORTS_DIR=str(pending)
            )
            command = ["pt_shell", "-f", "scripts/ptpx.tcl"]
            log = pending / "ptpx.log"
        print(f"[power {mode}] {scenario_id}: {log}", flush=True)
        with log.open("w") as output:
            exit_code = subprocess.run(
                command,
                cwd=workdir,
                env=tool_environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            ).returncode
        if mode == "simulate":
            complete = (
                saif_path.is_file()
                and saif_path.stat().st_size > 0
                and status_path.is_file()
                and status_path.read_text().strip() == "PASS"
            )
            if exit_code or not complete:
                status_path.write_text("FAIL\n")
                failed_scenarios.append(scenario_id)
        elif (
            exit_code
            or any(
                line.startswith(("Error:", "ERROR:"))
                for line in log.read_text(errors="replace").splitlines()
            )
            or not (pending / "power_flat.rpt").is_file()
        ):
            failed_scenarios.append(scenario_id)
        else:
            reports.parent.mkdir(exist_ok=True)
            pending.replace(
                reports
            )  # Only a completed tool process publishes gradeable reports.
    if failed_scenarios:
        print(f"[power {mode}] failed: {', '.join(failed_scenarios)}", flush=True)
    return int(bool(failed_scenarios))
