"""Exercise the deployed entrypoints and the evidence each operation replaces."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "skills/simulation/templates/infra"
CURRENT = (
    "result.json",
    "regression-log.txt",
    "case-results.json",
    "case-results-summary.md",
    "structural-coverage.json",
)


def setup(wd):
    shutil.copytree(INFRA, wd, dirs_exist_ok=True)
    (wd / "env.sh").write_text(
        (INFRA / "env.sh")
        .read_text()
        .replace("MY_MODULE", "sample")
        .replace("MY_TOP", "sample")
        + "\nvcs() { touch compiler-called; return 7; }\n"
        + 'urg() { printf "%s\\n" "$@" > urg-args; return 9; }\n'
    )
    (wd / "tests").mkdir(exist_ok=True)
    (wd / "tests/testlist.json").write_text(
        json.dumps(
            {
                "tests": [
                    {
                        "test_id": "T",
                        "uvm_testname": "sample_test",
                        "suites": ["smoke", "regress"],
                    }
                ]
            }
        )
    )
    for name in CURRENT:
        (wd / name).write_text("previous evidence")
    (wd / "regression-log.txt").write_text(
        "# seed: 11\nRESULT T PASS uvm_testname=sample_test log=logs/T.log\n"
    )
    for name in [
        "cov_elab.vdb",
        "cov_test/cov_sample_test_11.vdb",
        "cov_test/other_22.vdb",
        "cov_merge",
        "logs",
    ]:
        (wd / name).mkdir(parents=True, exist_ok=True)
        (wd / name / "data").write_text("retained")
    (wd / "simv").write_text(f"""#!{sys.executable}
import sys
from pathlib import Path
p = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('+IPD_STATUS_PATH='))
Path(p).write_text('PASS\\n')
""")
    (wd / "simv").chmod(0o755)
    return {**os.environ, "UVM_HOME": str(wd), "SEED": "11", "PYTHON": sys.executable}


def run(wd, env, mode):
    return subprocess.run(
        ["make", mode], cwd=wd, env=env, capture_output=True, text=True
    )


@pytest.mark.parametrize("failure", ["compile", "setup", "selection", "env"])
def test_failed_execution_withdraws_replaced_evidence(tmp_path, failure):
    env = setup(tmp_path)
    mode = "simv" if failure == "compile" else "smoke"
    if failure == "setup":
        env["UVM_HOME"] = str(tmp_path / "absent")
    elif failure == "selection":
        (tmp_path / "tests/testlist.json").write_text('{"tests":[]}')
    elif failure == "env":
        (tmp_path / "env.sh").write_text("return 5\n")
    p = run(tmp_path, env, mode)
    assert p.returncode != 0
    assert all(not (tmp_path / name).exists() for name in CURRENT)
    assert not (tmp_path / "cov_merge").exists()
    assert (tmp_path / "logs/data").read_text() == "retained"
    if failure == "compile":
        assert not (tmp_path / "simv").exists()
        assert not (tmp_path / "cov_test").exists()
        assert not (tmp_path / "cov_elab.vdb").exists()
    assert run(tmp_path, env, "summary").returncode != 0
    assert run(tmp_path, env, "coverage").returncode != 0


def test_run_replaces_same_test_seed_and_keeps_other_data(tmp_path):
    env = setup(tmp_path)
    p = run(tmp_path, env, "smoke")
    assert p.returncode == 0, p.stderr
    assert not (tmp_path / "compiler-called").exists()
    assert not (tmp_path / "cov_test/cov_sample_test_11.vdb").exists()
    assert (tmp_path / "cov_test/other_22.vdb/data").read_text() == "retained"
    assert "RESULT T PASS " in (tmp_path / "regression-log.txt").read_text()
    assert not (tmp_path / "case-results.json").exists()
    assert run(tmp_path, env, "summary").returncode == 0
    assert json.loads((tmp_path / "case-results.json").read_text())["passed_tests"] == 1


def test_coverage_can_combine_retained_seeds_without_uvm_or_recompilation(tmp_path):
    env = setup(tmp_path)
    env.update(UVM_HOME="", SEED="99")
    cases = (tmp_path / "case-results.json").read_bytes()
    p = run(tmp_path, env, "coverage")
    assert p.returncode != 0  # controlled URG failure after recording its arguments
    args = (tmp_path / "urg-args").read_text()
    assert "cov_test/cov_sample_test_11.vdb" in args
    assert "99" not in args and "other_22" in args and "*" not in args
    assert (tmp_path / "case-results.json").read_bytes() == cases
    assert not (tmp_path / "structural-coverage.json").exists()
    assert not (tmp_path / "result.json").exists()
    assert (tmp_path / "cov_test/other_22.vdb/data").exists()


def test_summary_failure_withdraws_counts_without_touching_coverage(tmp_path):
    env = setup(tmp_path)
    (tmp_path / "regression-log.txt").unlink()
    p = run(tmp_path, env, "summary")
    assert p.returncode != 0
    for name in ["result.json", "case-results.json", "case-results-summary.md"]:
        assert not (tmp_path / name).exists()
    assert (tmp_path / "structural-coverage.json").read_text() == "previous evidence"


def test_summary_reuses_evidence_without_a_simulation_environment(tmp_path):
    env = setup(tmp_path)
    env["UVM_HOME"] = ""
    p = run(tmp_path, env, "summary")
    assert p.returncode == 0, p.stderr
    assert json.loads((tmp_path / "case-results.json").read_text())["passed_tests"] == 1
    assert (tmp_path / "structural-coverage.json").read_text() == "previous evidence"
    assert not (tmp_path / "compiler-called").exists()
