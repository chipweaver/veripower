# tests/unit/test_power_bootstrap.py
"""power bootstrap verb — deploy-into-workdir behavior.

Two layers: in-process unit tests of infer_top_from_filelist (BP1), and subprocess
"mirror" tests of full deploy behavior (BP2-BP11 + the §8 cross-stage contract CS1).
The mirror runs the real shipped skill with cwd set to a tmp design-tree root and builds
the upstream asic/<module>/... references under it. The bootstrap anchors the design tree
on the CWD (matching state.py and the stage-subagent contract), independent of where the
skill code lives. The bootstrap shells out to the DEPLOYED emit_power_tests.py (Tier-2)
to render the initial power tests; a §8 violation there propagates as exit 1.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN = REPO_ROOT / "skills" / "power-analysis" / "scripts" / "power" / "__main__.py"
sys.path.insert(0, str(REPO_ROOT / "skills" / "power-analysis" / "scripts"))
from power import bootstrap  # noqa: E402


# ── BP1: infer_top_from_filelist (in-process, precise) ────────────────────────
def test_infer_top_from_filelist_basename(tmp_path):
    (tmp_path / "filelist.txt").write_text("rtl/foo.sv\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "foo"


def test_infer_top_from_filelist_skips_directives_and_comments(tmp_path):
    (tmp_path / "filelist.txt").write_text("# header\n+incdir+inc\ntop.v\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "top"


def test_infer_top_from_filelist_sequential_ext_strip(tmp_path):
    # chained .v/.sv/.vh strip, no break (a name ending '.sv.v' loses both):
    # foo.sv.v -> (strip .v) foo.sv -> (strip .sv) foo
    (tmp_path / "filelist.txt").write_text("foo.sv.v\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "foo"


def test_infer_top_from_filelist_none_when_absent(tmp_path):
    assert bootstrap.infer_top_from_filelist(tmp_path) is None


# ── BP2-BP11 + CS1: full deploy (subprocess mirror) ───────────────────────────
_VALID_SCAFFOLD = {
    "sequences": [{"name": "idle_seq", "agent": "cpu"}],
    "power_scenarios": [
        {
            "id": "S1",
            "sequence_ref": "idle_seq",
            "scenario": "idle",
            "duration_cycles": 1000,
        }
    ],
}


def _make_tree(
    tmp_path,
    *,
    top="dut",
    with_rtl_filelist=True,
    with_netlist=True,
    with_sim_filelist=True,
    with_scaffold=True,
    scaffold=None,
):
    """Build the upstream asic/<module>/... references under a tmp design-tree root.
    Returns (module, workdir, main). Deploy tests run `main` (the real shipped skill)
    with cwd=tmp_path, so the bootstrap anchors the design tree on the CWD."""
    m = "M"
    base = tmp_path / "asic" / m
    rtl = base / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    if with_rtl_filelist:
        (rtl / "filelist.txt").write_text(f"rtl/{top}.v\n")
    syn_out = base / "Design" / "synthesis" / "out"
    syn_out.mkdir(parents=True)
    if with_netlist:
        (syn_out / f"{top}_syn.v").write_text("// netlist\n")
    sim = base / "Verification" / "simulation"
    sim.mkdir(parents=True)
    if with_sim_filelist:
        (sim / "filelist.f").write_text("// tb filelist\n")
    plan = base / "Verification" / "simulation-plan"
    plan.mkdir(parents=True)
    if with_scaffold:
        (plan / "scaffold-specification.json").write_text(
            json.dumps(_VALID_SCAFFOLD if scaffold is None else scaffold)
        )
    workdir = base / "Verification" / "power-analysis" / "runs" / "1"
    return m, workdir, _MAIN


def _run(module, workdir, main, extra=None, cwd=None):
    if cwd is None:
        # The bootstrap anchors the design tree on the CWD; the tree root is the
        # prefix of the (absolute) workdir up to the 'asic/' component.
        parts = Path(workdir).parts
        cwd = Path(*parts[: parts.index("asic")])
    cmd = [
        "python3",
        str(main),
        "bootstrap",
        "--module",
        module,
        "--workdir",
        str(workdir),
    ]
    if extra:
        cmd += extra
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def test_deploys_and_substitutes(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    env_sh = (workdir / "env.sh").read_text()
    assert "MY_TOP" not in env_sh and "MY_MODULE" not in env_sh
    assert "MY_SYN_OUT" not in env_sh
    assert (workdir / "Makefile").is_file()
    # the contract-locked DUT_INST/TB_TOP lines (no MY_* token) survive untouched
    assert 'DUT_INST="u_dut"' in env_sh
    assert 'TB_TOP="${TOP}_tb_top"' in env_sh


def test_relpath_substituted_for_external_dirs(tmp_path):
    # BP6: MY_SYN_OUT / MY_SIM_DIR / MY_PLAN_DIR -> relpath(target, workdir), which
    # from runs/1/ climbs out with '..' segments. (The placeholder must be gone and a
    # relative path to the external dir present.)
    m, workdir, main = _make_tree(tmp_path)
    assert _run(m, workdir, main, extra=["--top", "dut"]).returncode == 0
    env_sh = (workdir / "env.sh").read_text()
    assert "MY_SIM_DIR" not in env_sh and "MY_PLAN_DIR" not in env_sh
    assert "../" in env_sh  # relpath climbs out of runs/<N>/
    # NB: assert the BARE dir name, not "Verification/simulation-plan". relpath from
    # runs/<N>/ to a sibling under the shared Verification/ ancestor is
    # "../../../simulation-plan" — the "Verification/" segment is consumed by the
    # "../" climb, so it is NOT in the string. (Design/synthesis/out survives whole
    # below only because Design is a *different* top-level subtree than Verification.)
    assert "../../../simulation-plan" in env_sh  # MY_PLAN_DIR -> relpath
    assert (
        "Design/synthesis/out" in env_sh
    )  # MY_SYN_OUT -> relpath (climbs to asic/<m>)


def test_infer_top_used_when_top_omitted(tmp_path):
    # No --top: TOP inferred from rtl-design/filelist.txt first entry ('dut').
    m, workdir, main = _make_tree(
        tmp_path
    )  # filelist.txt -> rtl/dut.v, netlist dut_syn.v
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 0, r.stderr
    env_sh = (workdir / "env.sh").read_text()
    assert 'export TOP="${TOP:-dut}"' in env_sh


def test_renders_power_tests(tmp_path):
    # BP9 happy path: the deployed emit_power_tests.py renders one test per unique
    # sequence_ref + the power_filelist.f. (idle_seq -> power_idle_seq_test.sv.)
    m, workdir, main = _make_tree(tmp_path)
    assert _run(m, workdir, main, extra=["--top", "dut"]).returncode == 0
    assert (workdir / "scaffold" / "power_filelist.f").is_file()
    assert (workdir / "scaffold" / "power_tests" / "power_idle_seq_test.sv").is_file()


def test_emit_failure_propagates_exit1(tmp_path):
    # CS1 / BP9 fail: a power_scenarios[].sequence_ref with no matching sequences[].name
    # makes the (untouched, Tier-2) emit_power_tests.py fail closed (exit 1) on the
    # §8 cross-stage contract; the bootstrap propagates it as exit 1 and surfaces stderr.
    bad = {
        "sequences": [],
        "power_scenarios": [{"id": "S1", "sequence_ref": "missing_seq"}],
    }
    m, workdir, main = _make_tree(tmp_path, scaffold=bad)
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 1
    assert (
        "sequence_ref" in r.stderr
    )  # emit_power_tests' actionable cross-stage message


def test_cant_infer_top_fail_closed(tmp_path):
    # No --top and no usable RTL entry in filelist.txt -> inference None -> exit 1.
    m, workdir, main = _make_tree(tmp_path, with_rtl_filelist=False)
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 1
    assert "cannot infer" in r.stderr


def test_already_deployed_guard(tmp_path):
    m, workdir, main = _make_tree(tmp_path)
    assert _run(m, workdir, main, extra=["--top", "dut"]).returncode == 0
    r2 = _run(m, workdir, main, extra=["--top", "dut"])
    assert r2.returncode == 1
    assert "already deployed" in r2.stderr


def test_fail_closed_when_netlist_missing(tmp_path):
    # --top given so we get past inference; missing netlist -> exit 1.
    # The pre-flight runs BEFORE copytree, so a missing upstream ref leaves no
    # partial deploy (no Makefile) — the user's retry is clean, not "already deployed".
    m, workdir, main = _make_tree(tmp_path, with_netlist=False)
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 1
    assert "netlist not found" in r.stderr
    assert not (workdir / "Makefile").exists()


def test_fail_closed_when_sim_filelist_missing(tmp_path):
    m, workdir, main = _make_tree(tmp_path, with_sim_filelist=False)
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 1
    assert "TB filelist not found" in r.stderr
    assert not (workdir / "Makefile").exists()


def test_fail_closed_when_scaffold_missing(tmp_path):
    m, workdir, main = _make_tree(tmp_path, with_scaffold=False)
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 1
    assert "simulation-plan not found" in r.stderr
    assert not (workdir / "Makefile").exists()


def test_retry_after_fixing_upstream_succeeds(tmp_path):
    # The should-fix scenario: bootstrap with a missing netlist fails cleanly; the
    # user then produces the netlist and re-runs the SAME workdir — it must deploy,
    # not trip the "already deployed" guard from a leftover partial copytree.
    m, workdir, main = _make_tree(tmp_path, with_netlist=False)
    assert _run(m, workdir, main, extra=["--top", "dut"]).returncode == 1
    (tmp_path / "asic" / m / "Design" / "synthesis" / "out" / "dut_syn.v").write_text(
        "// netlist\n"
    )
    r2 = _run(m, workdir, main, extra=["--top", "dut"])
    assert r2.returncode == 0, r2.stderr
    assert (workdir / "Makefile").is_file()


def test_missing_template_dir_fail_closed(tmp_path):
    # Run a skill COPY whose templates/ has been removed -> fail-closed before any
    # mutation. The design tree itself is valid under the CWD.
    m, workdir, _ = _make_tree(tmp_path)
    skill_copy = tmp_path / "skills" / "power-analysis"
    shutil.copytree(REPO_ROOT / "skills" / "power-analysis", skill_copy)
    shutil.rmtree(skill_copy / "templates")
    main = skill_copy / "scripts" / "power" / "__main__.py"
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 1
    assert "missing" in r.stderr
    assert not (workdir / "Makefile").exists()  # fail-closed before any mutation


def test_relative_workdir_with_trailing_slash(tmp_path):
    # BP4: a relative --workdir resolves against the CWD (the design-tree root), and the
    # trailing slash is dropped (type=Path) before deploy.
    m, workdir, main = _make_tree(tmp_path)
    proc = subprocess.run(
        [
            "python3",
            str(main),
            "bootstrap",
            "--module",
            m,
            "--workdir",
            "asic/M/Verification/power-analysis/runs/1/",  # relative + trailing slash
            "--top",
            "dut",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (workdir / "Makefile").is_file()  # resolved to the absolute location
    assert (workdir / "env.sh").is_file()
