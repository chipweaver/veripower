# tests/unit/test_power_bootstrap.py
"""power bootstrap verb — deploy-into-workdir behavior.

Subprocess "mirror" tests of full deploy behavior plus the sim-plan->power
cross-stage contract. The mirror runs the real shipped skill with cwd set to a tmp
design-tree root and builds the upstream asic/<module>/... references under it,
pre-populating workdir/dispatch.json (netlist/tb_env/scaffold/ppa keys) the way
kernel.py dispatch injects it at dispatch time — bootstrap reads the upstream
stage-root locations from dispatch.json instead of self-navigating
tree_root/asic/<module>/Design|Verification/<stage>. Power has no rtl key (it
never consumes rtl-design; TOP is inferred from the injected netlist's
out/*_syn.v, same mechanism as timing.infer_top). The bootstrap shells out to the
DEPLOYED emit_power_tests.py (Tier-2) to render the initial power tests; a contract
violation there propagates as exit 1.
"""

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN = REPO_ROOT / "skills" / "power-analysis" / "scripts" / "power" / "__main__.py"


# ── full deploy + cross-stage contract (subprocess mirror) ───────────────────────────
_VALID_SCAFFOLD = {
    "sequences": [{"name": "idle_seq", "agent": "cpu"}],
    "power_scenarios": [
        {
            "id": "S1",
            "sequence_ref": "idle_seq",
            "scenario": "idle",
        }
    ],
}


def _make_tree(
    tmp_path,
    *,
    top="dut",
    with_netlist=True,
    with_sim_filelist=True,
    with_scaffold=True,
    scaffold=None,
):
    """Build the upstream synthesis/tb_env/scaffold trees under a tmp design-tree
    root, and pre-populate workdir/dispatch.json (netlist/tb_env/scaffold/ppa keys)
    the way kernel.py dispatch injects it at dispatch time. Bootstrap reads the
    upstream stage-root locations from dispatch.json instead of self-navigating
    tree_root/asic/<module>/Design|Verification/<stage> — power has no rtl key
    (it never consumes rtl-design; TOP is inferred from the injected netlist).

    Returns (module, workdir, main). Deploy tests run `main` (the real shipped
    skill) with cwd=tmp_path, so the bootstrap anchors the design tree on the CWD.
    """
    m = "M"
    base = tmp_path / "asic" / m
    syn = base / "Design" / "synthesis"
    syn_out = syn / "out"
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
        doc = _VALID_SCAFFOLD if scaffold is None else scaffold
        (plan / "sequences.json").write_text(json.dumps(doc.get("sequences", [])))
        (plan / "power-scenarios.json").write_text(
            json.dumps(doc.get("power_scenarios", []))
        )
    workdir = base / "Verification" / "power-analysis" / "runs" / "1"
    workdir.mkdir(parents=True)
    (workdir / "dispatch.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "netlist": str(syn),
                    "tb_env": str(sim),
                    "scaffold": str(plan),
                    "ppa": str(base / "Design" / "specification"),
                }
            }
        )
    )
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


def test_env_sh_uses_absolute_dirs_from_dispatch_json(tmp_path):
    # MY_SYN_OUT / MY_SIM_DIR / MY_PLAN_DIR now come straight from the injected
    # dispatch.json stage roots (absolute) — no os.path.relpath, no '/../' hop,
    # regardless of workdir depth.
    m, workdir, main = _make_tree(tmp_path)
    netlist_root = tmp_path / "asic" / m / "Design" / "synthesis"
    tb_env_root = tmp_path / "asic" / m / "Verification" / "simulation"
    r = _run(m, workdir, main, extra=["--top", "dut"])
    assert r.returncode == 0, r.stderr
    env = (workdir / "env.sh").read_text()
    assert f'export NETLIST="{netlist_root}/out/' in env
    assert f'export TB_DIR="{tb_env_root}"' in env
    assert "os.path.relpath" not in env  # (sanity: no relpath token leaked)
    # and the bootstrap emitted no '..' relative hop
    assert "/../" not in env


def test_top_inferred_from_netlist_not_rtl_design(tmp_path):
    # no --top, no rtl key in dispatch.json → TOP comes from synthesis out/<TOP>_syn.v
    # Assert bootstrap succeeds and never touches Design/rtl-design.
    m, workdir, main = _make_tree(tmp_path, top="dut")  # netlist -> dut_syn.v
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 0, r.stderr  # inferred TOP from the injected netlist
    assert "rtl" not in json.loads(
        (workdir / "dispatch.json").read_text()
    )  # power has no rtl key
    env_sh = (workdir / "env.sh").read_text()
    assert 'export TOP="${TOP:-dut}"' in env_sh
    # power never self-navigates to (nor even requires) Design/rtl-design
    assert not (tmp_path / "asic" / m / "Design" / "rtl-design").exists()


def test_renders_power_tests(tmp_path):
    # Happy path: the deployed emit_power_tests.py renders one test per unique
    # sequence_ref + the power_filelist.f. (idle_seq -> power_idle_seq_test.sv.)
    m, workdir, main = _make_tree(tmp_path)
    assert _run(m, workdir, main, extra=["--top", "dut"]).returncode == 0
    assert (workdir / "scaffold" / "power_filelist.f").is_file()
    assert (workdir / "scaffold" / "power_tests" / "power_idle_seq_test.sv").is_file()


def test_emit_failure_propagates_exit1(tmp_path):
    # Fail: a power_scenarios[].sequence_ref with no matching sequences[].name
    # makes the (untouched, Tier-2) emit_power_tests.py fail closed (exit 1) on the
    # Cross-stage contract; the bootstrap propagates it as exit 1 and surfaces stderr.
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
    # No --top and no synthesis netlist (out/*_syn.v) -> inference None -> exit 1.
    m, workdir, main = _make_tree(tmp_path, with_netlist=False)
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 1
    assert "cannot infer" in r.stderr


def test_two_netlists_fail_closed_rather_than_picking_one(tmp_path):
    # An ambiguous out/*_syn.v set used to resolve to whichever name sorted first, so a
    # run could analyse a design nobody asked about and report a power_mw for it. Exactly
    # one match or nothing; --top is the way out of the ambiguity, not a way past it.
    m, workdir, main = _make_tree(tmp_path, top="dut")
    out = tmp_path / "asic" / m / "Design" / "synthesis" / "out"
    (out / "aaa_syn.v").write_text("module aaa; endmodule\n")
    r = _run(m, workdir, main)  # no --top
    assert r.returncode == 1
    assert "2 out/*_syn.v" in r.stderr
    assert not (workdir / "Makefile").exists()  # nothing deployed, so the retry is open
    # and naming one resolves it
    assert _run(m, workdir, main, extra=["--top", "dut"]).returncode == 0


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
    assert "simulation-plan sidecar not found" in r.stderr
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
    # A relative --workdir resolves against the CWD (the design-tree root), and the
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


# ── the deployed shell's contract with the Makefile that calls it ────────────────────────
def test_run_gls_power_accepts_the_plan_stage_root(tmp_path):
    """The Makefile passes PLAN_DIR — the simulation-plan stage root — and
    extract_power_scenarios.py reads power-scenarios.json out of it. The guard tested for a
    file, left over from when the plan was one scaffold-specification.json, so gls-run could
    not start on any module. Reaching the tools takes real EDA; what is checkable here is
    that the guard admits what the only caller passes."""
    import subprocess

    script = REPO_ROOT / "skills/power-analysis/templates/scripts/run_gls_power.sh"
    plan = tmp_path / "simulation-plan"
    plan.mkdir()
    (plan / "power-scenarios.json").write_text("[]")
    simv = tmp_path / "simv"
    simv.write_text("#!/bin/sh\nexit 0\n")
    simv.chmod(0o755)
    r = subprocess.run(
        [
            "bash",
            str(script),
            "--plan",
            str(plan),
            "--saif-dir",
            str(tmp_path / "saif"),
            "--simv",
            str(simv),
            "--log",
            str(tmp_path / "log.txt"),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert "not a directory" not in r.stderr, r.stderr
    assert "--plan not found" not in r.stderr, r.stderr


def test_run_gls_power_rejects_a_file_as_plan(tmp_path):
    import subprocess

    script = REPO_ROOT / "skills/power-analysis/templates/scripts/run_gls_power.sh"
    f = tmp_path / "power-scenarios.json"
    f.write_text("[]")
    r = subprocess.run(
        [
            "bash",
            str(script),
            "--plan",
            str(f),
            "--saif-dir",
            str(tmp_path / "saif"),
            "--simv",
            "/bin/true",
            "--log",
            str(tmp_path / "log.txt"),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert r.returncode != 0 and "not a directory" in r.stderr
