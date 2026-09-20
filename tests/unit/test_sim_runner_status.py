"""The shell runner combines completed test status with process success."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "skills/simulation/templates/infra"


@pytest.mark.parametrize(
    "status,exit_code,expected",
    [
        ("PASS", 0, "PASS"),
        ("FAIL", 0, "FAIL"),
        ("PASS", 7, "FAIL"),
        (None, 0, "FAIL"),
        (None, 7, "FAIL"),
    ],
)
def test_completed_status_and_process_exit(tmp_path, status, exit_code, expected):
    shutil.copytree(INFRA / "scripts", tmp_path / "scripts")
    (tmp_path / "env.sh").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/testlist.json").write_text(
        json.dumps(
            {
                "tests": [
                    {
                        "test_id": "probe",
                        "uvm_testname": "probe_test",
                        "suites": ["smoke"],
                    }
                ]
            }
        )
    )
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/probe.status").write_text("PASS\n")
    simv = tmp_path / "simv"
    simv.write_text(f"""#!{sys.executable}
import os,sys
from pathlib import Path
status_path=next(x.split('=',1)[1] for x in sys.argv if x.startswith('+IPD_STATUS_PATH='))
status={status!r}
if status is not None: Path(status_path).write_text(status+'\\n')
Path(os.environ['IPD_FSDB_FILE']).write_text('waveform')
sys.exit({exit_code})
""")
    simv.chmod(0o755)
    env = {
        **os.environ,
        "PYTHON": sys.executable,
        "UVM_HOME": str(tmp_path),
        "TESTLIST_JSON": "tests/testlist.json",
        "VCS_COV": "",
        "SEED": "1",
        "MODULE": "probe",
        "TOP": "probe",
        "RUN_LOG_DIR": "logs",
        "SIMV": "simv",
    }
    r = subprocess.run(
        ["bash", "scripts/run_vcs_regression.sh", "smoke"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert f"RESULT probe {expected} " in (tmp_path / "regression-log.txt").read_text()
    assert (tmp_path / "probe.fsdb").exists() == (expected == "FAIL")
