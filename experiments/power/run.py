#!/usr/bin/env python3
"""Exercise the power stage against an existing FSA or microgpt implementation.

Requires actual VCS/PT setup (LIB_V, LIB_DB). No RTL generation or functional regression.
"""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "skills/power-analysis/scripts/power/__main__.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("fsa", "microgpt"), required=True)
    parser.add_argument("--synthesis", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--sdf", type=Path, help="matching SDF export for this simulator"
    )
    args = parser.parse_args()
    wd = args.out.resolve()
    wd.mkdir(parents=True, exist_ok=False)
    plan, spec = wd / "plan", wd / "spec"
    plan.mkdir()
    spec.mkdir()
    (plan / "power-scenarios.json").write_text(
        json.dumps([{"id": s} for s in ("stopped", "clocked", "active")])
    )
    (plan / "verification-plan.md").write_text(
        "Reset-held stopped/clocked baselines: 1000ns after settling, defined inputs. "
        "Active: FSA two causal modes and 32 reference-checked outputs; microgpt three "
        "reference-checked greedy tokens from pos0. Initialization excluded. "
        "These are focused refactor experiments, not peak or representative workload estimates. "
        "No power budget. Check the actual clock constraints against the TB before use.\n"
    )
    (spec / "requirements.json").write_text("[]\n")
    (wd / "dispatch.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "netlist": str(args.synthesis.resolve()),
                    "plan": str(plan),
                    "requirements": str(spec),
                }
            }
        )
    )
    subprocess.run(["python3", str(CLI), "bootstrap", "--workdir", str(wd)], check=True)
    with (wd / "env.sh").open("a") as stream:
        for key in ("LIB_DB", "LIB_V"):
            stream.write(f"\nexport {key}={shlex.quote(os.environ[key])}\n")
        stream.write("export STRIP_PATH=power_probe/measured_device\n")
        if args.sdf:
            stream.write(
                "export SDF_FILE=" + shlex.quote(str(args.sdf.resolve())) + "\n"
            )
    shutil.copyfile(
        Path(__file__).with_name(args.case + ".sv"), wd / "experiment/tb.sv"
    )
    (wd / "experiment/compile.sh").write_text(
        "set -euo pipefail\n"
        "vcs -full64 +neg_tchk -sverilog -debug_access+all -timescale=1ns/1ps "
        '-top power_probe -sdf max:power_probe.measured_device:"$SDF_FILE" '
        'experiment/tb.sv "$NETLIST" "$LIB_V" '
        + shlex.quote(str(args.reference.resolve()))
        + " -CFLAGS -std=gnu99 -LDFLAGS -lm -o simv\n"
    )
    (wd / "experiment/run.sh").write_text(
        'set -euo pipefail\nexec ./simv +CASE="$1" +SAIF="$2" +STATUS="$3"\n'
    )
    sources = [args.reference, Path(os.environ["LIB_V"])] + list(
        (args.synthesis / "out").glob("*_syn.*")
    )
    if args.sdf:
        sources.append(args.sdf)
    (wd / "source-fingerprints.json").write_text(
        json.dumps(
            {
                str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources
            },
            indent=2,
        )
    )
    rc = 0
    for action in ("compile", "simulate", "calculate"):
        with (wd / f"{action}.log").open("w") as stream:
            rc = subprocess.run(
                [
                    "bash",
                    "-c",
                    '. ./env.sh; exec python3 "$1" "$2" --workdir .',
                    "power-bench",
                    str(CLI),
                    action,
                ],
                cwd=wd,
                stdout=stream,
                stderr=subprocess.STDOUT,
            ).returncode
        if rc:
            break
    command = ["python3", str(CLI), "finalize", "--workdir", str(wd)]
    if rc:
        command += [
            "--fail-reason",
            "Power experiment did not complete; see execution and per-scenario logs.",
        ]
    subprocess.run(command, check=True)
    return int(
        rc != 0 or json.loads((wd / "result.json").read_text())["status"] != "pass"
    )


if __name__ == "__main__":
    raise SystemExit(main())
