# tests/unit/test_sim_bootstrap.py
"""sim bootstrap verb — deploy-into-workdir behavior.

Two layers: in-process unit tests of the TOP-inference helpers (byte-for-byte the
lintcdc helpers), and subprocess "mirror" tests of full deploy behavior that run the real
shipped skill with cwd set to a tmp design-tree root and build the upstream
asic/<module>/Design/... references under it. The bootstrap anchors the design tree on the
CWD (matching kernel.py and the stage-subagent contract), independent of where the skill
code lives.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN = REPO_ROOT / "skills" / "simulation" / "scripts" / "sim" / "__main__.py"
sys.path.insert(0, str(REPO_ROOT / "skills" / "simulation" / "scripts"))
from sim import bootstrap  # noqa: E402


# ── TOP: one source, indexed (in-process) ──────────────────────────────────────
def test_top_comes_from_the_scaffold_input(tmp_path):
    # The same field sim.scaffold indexes to name <top>_tb_top.sv, so the substituted
    # MY_TOP and the rendered top cannot disagree.
    (tmp_path / "tb-scaffold.json").write_text(
        json.dumps({"top": "my_top", "module": "m"})
    )
    assert bootstrap.read_top(tmp_path) == "my_top"


def _mirror(
    tmp_path,
    *,
    rtl_files={"c": {"files": ["rtl/dut.v"], "incdirs": ["inc"]}},
    scaffold_top="dut",
):
    """Seed the upstream rtl-design references + a tb-scaffold.json (`top`
    field) under a tmp design-tree root, and pre-populate workdir/dispatch.json
    (rtl/plan/scaffold keys) the way kernel.py dispatch injects it at dispatch time
    (+ carry_self, which would already have placed any carried TB directly into
    workdir before this verb runs). Returns
    (main, workdir, module); deploy tests run `main` (the real shipped skill) with
    cwd=tmp_path, so the bootstrap anchors the design tree (and a relative --workdir)
    on the CWD. bootstrap reads the rtl-design / scaffold stage roots from dispatch.json,
    not by self-navigating tree_root/asic/<module>/Design/... or .../specification."""
    module = "tpu_top"
    rtl = tmp_path / "asic" / module / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    (rtl / "rtl-files.json").write_text(json.dumps(rtl_files))
    plan_root = tmp_path / "asic" / module / "Verification" / "simulation-plan"
    plan_root.mkdir(parents=True)
    (plan_root / "tb-scaffold.json").write_text(json.dumps({"top": scaffold_top}))
    spec_root = tmp_path / "asic" / module / "Design" / "specification"
    spec_root.mkdir(parents=True)
    (spec_root / "top-io.json").write_text(
        json.dumps(
            [
                {
                    "name": "clk",
                    "direction": "input",
                    "width": 1,
                    "clock_domain": "clk",
                    "interface_group": "bench",
                    "role": "clock",
                },
                {
                    "name": "rst_n",
                    "direction": "input",
                    "width": 1,
                    "clock_domain": "clk",
                    "interface_group": "bench",
                    "role": "reset",
                    "reset_polarity": 0,
                    "reset_kind": "async",
                },
                {
                    "name": "req",
                    "direction": "input",
                    "width": 1,
                    "clock_domain": "clk",
                    "interface_group": "drv_g",
                    "role": "data",
                },
            ]
        )
    )
    (spec_root / "clocks.json").write_text(
        json.dumps([{"name": "clk", "period_ns": 10.0, "relationship": "primary"}])
    )
    workdir = tmp_path / "asic" / module / "Verification" / "simulation" / "runs" / "1"
    workdir.mkdir(parents=True)
    (workdir / "dispatch.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "rtl": str(rtl),
                    "plan": str(plan_root),
                    "scaffold": str(plan_root),
                    "spec": str(spec_root),
                }
            }
        )
    )
    return _MAIN, workdir, module


def _run(main, module, workdir, *extra):
    # The bootstrap anchors the design tree on the CWD; the tree root is the prefix of
    # the (absolute) workdir up to the 'asic/' component.
    parts = Path(workdir).parts
    cwd = Path(*parts[: parts.index("asic")])
    return subprocess.run(
        [
            "python3",
            str(main),
            "bootstrap",
            "--module",
            module,
            "--workdir",
            str(workdir),
            *extra,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_bootstrap_deploys_infra_and_dirs(tmp_path):
    main, wd, module = _mirror(tmp_path)
    r = _run(main, module, wd)
    assert r.returncode == 0, r.stderr
    assert (wd / "Makefile").is_file()
    assert (wd / "env.sh").is_file()
    for d in (
        "interface",
        "transaction",
        "agent",
        "checker",
        "refmodel",
        "env",
        "seq",
        "test",
        "pkg",
        "top",
    ):
        assert (wd / "tb" / "uvm" / d).is_dir()
    assert (wd / "tests").is_dir()
    assert (wd / "rtl_filelist.f").is_file()


def test_bootstrap_substitutes_my_placeholders(tmp_path):
    main, wd, module = _mirror(tmp_path)
    _run(main, module, wd)
    env = (wd / "env.sh").read_text()
    assert "MY_TOP" not in env and "MY_MODULE" not in env
    # RTL_DIR was dropped as a vestigial export (unconsumed anywhere in the stage;
    # rtl_filelist.f, always regenerated absolute, is the load-bearing RTL reference).
    assert "RTL_DIR" not in env


def test_bootstrap_writes_rtl_filelist_rebased(tmp_path):
    main, wd, module = _mirror(tmp_path)
    _run(main, module, wd)
    fl = (wd / "rtl_filelist.f").read_text()
    assert "Design/rtl-design/rtl/dut.v" in fl


def test_rtl_filelist_reanchors_to_absolute(tmp_path):
    # bootstrap reads the upstream rtl-design location from the injected dispatch.json
    # "rtl" key — not by self-navigating tree_root/asic/<module>/.... rtl_filelist.f
    # must bake the ABSOLUTE rtl root, never a relative climb.
    main, wd, module = _mirror(tmp_path)
    rtl_root = tmp_path / "asic" / module / "Design" / "rtl-design"
    _run(main, module, wd)
    f = (wd / "rtl_filelist.f").read_text()
    assert str(rtl_root) in f and "../../../rtl-design" not in f


def test_bootstrap_infra_only_without_scaffold(tmp_path):
    main, wd, module = _mirror(tmp_path)
    _run(main, module, wd)
    # no scaffold spec -> no rendered tb/uvm/**/*.sv (dirs exist, but empty)
    assert not list((wd / "tb" / "uvm" / "interface").glob("*.sv"))


def test_bootstrap_renders_scaffold_when_given(tmp_path):
    main, wd, module = _mirror(tmp_path)
    spec = {
        "module": module,
        "top": "dut",
        "agents": [{"name": "drv", "mode": "active", "interface_groups": ["drv_g"]}],
        "sequences": [{"name": "smoke", "agent": "drv"}],
        "tests": [
            {
                "name": "t",
                "seqs": ["smoke"],
                "feature": "F-1",
                "test_id": "T-1",
                "suites": ["regress"],
                "feature_name": "Register write path",
            }
        ],
    }
    plan_dir = wd.parent  # any readable dir doubles as the plan dir
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "sequences.json").write_text(json.dumps(spec.pop("sequences")))
    (plan_dir / "tb-scaffold.json").write_text(json.dumps(spec))
    r = _run(main, module, wd, "--plan", str(plan_dir))
    assert r.returncode == 0, r.stderr
    # interface files are named by module ({module}_{agent}_if.sv), not by top
    assert (wd / f"tb/uvm/interface/{module}_drv_if.sv").is_file()


def test_makefile_present_is_rework_not_abort(tmp_path):
    # pre-place a carried Makefile (as kernel.py's carry_self would, BEFORE this verb
    # runs) -> existence, not abort: rc==0 (rework), and no-clobber preserves it.
    main, wd, module = _mirror(tmp_path)
    (wd / "Makefile").write_text("carried")
    r = _run(main, module, wd)
    assert r.returncode == 0, r.stderr
    assert (wd / "Makefile").read_text() == "carried"


def test_bootstrap_allows_hint_only_workdir(tmp_path):
    main, wd, module = _mirror(tmp_path)
    (wd / "orchestrator-context.md").write_text("hints\n")  # not a Makefile
    r = _run(main, module, wd)
    assert r.returncode == 0, r.stderr
    assert (wd / "Makefile").is_file()


def test_bootstrap_unusable_top_exit_1(tmp_path):
    # `top` is typed as a bare string upstream, so a name that cannot be a module
    # identifier is schema-legal and this is the only place it is reported. Left through,
    # it lands in generated SV as a syntax error nobody wrote by hand.
    main, wd, module = _mirror(tmp_path, scaffold_top="dut-1 top")
    r = _run(main, module, wd)
    assert r.returncode == 1 and "not a Verilog identifier" in r.stderr


def test_placeholders_are_substituted_only_in_what_was_deployed(tmp_path):
    # A carried file had its placeholders substituted the round it was deployed, so the
    # literal text can only be there because an author wrote it. Scanning the whole workdir
    # would rewrite that, and would read every binary the tools left in the run directory.
    main, wd, module = _mirror(tmp_path)
    carried = wd / "tb" / "uvm" / "checker" / "keep.sv"
    carried.parent.mkdir(parents=True, exist_ok=True)
    carried.write_text("// a check the author wrote about MY_TOP naming\n")
    (wd / "simv.eda-bin").write_bytes(b"\x7fELF\x02\x01\x01\x00\xff\xfe binary")
    r = _run(main, module, wd)
    assert r.returncode == 0, r.stderr
    assert carried.read_text() == "// a check the author wrote about MY_TOP naming\n"
    assert "MY_TOP" not in (wd / "env.sh").read_text()


def test_bootstrap_missing_scaffold_file_exit_1(tmp_path):
    main, wd, module = _mirror(tmp_path)
    r = _run(main, module, wd, "--plan", str(tmp_path / "nope"))
    assert r.returncode == 1 and "tb-scaffold.json" in r.stderr


def test_pycache_beside_the_templates_is_not_deployed(tmp_path):
    # Running the deployed scripts under test leaves __pycache__ in the template tree.
    # Copying it would ship stale bytecode into every workdir, and scripts/ is a promoted
    # artifact, so it would reach canonical too.
    main, wd, module = _mirror(tmp_path)
    assert _run(main, module, wd).returncode == 0
    assert not list(wd.rglob("__pycache__"))


def test_bootstrap_chmods_scripts(tmp_path):
    import os

    main, wd, module = _mirror(tmp_path)
    _run(main, module, wd)
    for sh in (wd / "scripts").glob("*.sh"):
        assert os.access(sh, os.X_OK)
