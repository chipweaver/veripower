# tests/unit/test_sim_bootstrap.py
"""sim bootstrap verb — deploy-into-workdir behavior.

Two layers: in-process unit tests of the TOP-inference helpers (B1 — byte-for-byte the
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


# ── B1: TOP-inference helpers (in-process) ─────────────────────────────────────
def test_top_from_manifest_module_field(tmp_path):
    # D6/G4: top is read from manifest.module (authoritative, spec §4.3), not README prose.
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "my_top", "children": []})
    )
    assert bootstrap.infer_top_from_manifest(tmp_path) == "my_top"


def test_top_from_manifest_absent_or_no_module(tmp_path):
    assert bootstrap.infer_top_from_manifest(tmp_path) is None  # no manifest
    (tmp_path / "manifest.json").write_text(json.dumps({"children": []}))  # no module
    assert bootstrap.infer_top_from_manifest(tmp_path) is None


def test_top_from_filelist_first_rtl_basename(tmp_path):
    (tmp_path / "filelist.txt").write_text("# c\n+incdir+inc\nrtl/my_top.sv\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) == "my_top"


def test_top_from_filelist_rejects_directive(tmp_path):
    (tmp_path / "filelist.txt").write_text("+incdir+include\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) is None


def test_top_from_filelist_rejects_padded_bare_name(tmp_path):
    # A whitespace-padded bare filename (no path separator) must NOT infer a top:
    # basename keeps the leading spaces, so the identifier check rejects it — byte-for-byte
    # the shell/lint-cdc behavior (no .strip() before basename).
    (tmp_path / "filelist.txt").write_text("  top.v\n")
    assert bootstrap.infer_top_from_filelist(tmp_path) is None


# ── full deploy "mirror" tests (subprocess; isolated repo root) ───────────────
def _mirror(
    tmp_path,
    *,
    readme="**Top module**: dut\n",
    filelist="rtl/dut.v\n+incdir+inc\n",
    manifest=None,
):
    """Seed the upstream rtl-design references under a tmp design-tree root. Returns
    (main, workdir, module); deploy tests run `main` (the real shipped skill) with
    cwd=tmp_path, so the bootstrap anchors the design tree on the CWD."""
    module = "tpu_top"
    rtl = tmp_path / "asic" / module / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    (rtl / "README.md").write_text(readme)
    (rtl / "filelist.txt").write_text(filelist)
    spec = tmp_path / "asic" / module / "Design" / "specification"
    spec.mkdir(parents=True)
    # top now comes from manifest.module (D6); seed it (matches the "dut" the fixtures expect).
    # Pass manifest={"children": []} (no module) to model an uninferrable top.
    (spec / "manifest.json").write_text(
        json.dumps(
            manifest if manifest is not None else {"module": "dut", "children": []}
        )
    )
    workdir = tmp_path / "asic" / module / "Verification" / "simulation" / "runs" / "1"
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
    assert "MY_RTL_DIR" not in env and "MY_SPEC_DIR" not in env
    # relpath workdir -> rtl-design carries '..' segments (str.replace, no sed hazard)
    assert "../../../../Design/rtl-design" in env or "../" in env


def test_bootstrap_writes_rtl_filelist_rebased(tmp_path):
    main, wd, module = _mirror(tmp_path)
    _run(main, module, wd)
    fl = (wd / "rtl_filelist.f").read_text()
    assert "Design/rtl-design/rtl/dut.v" in fl


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
        "primary_clock": {"dut_port_name": "clk", "period_ns": 10.0},
        "reset": {"dut_port_name": "rst_n"},
        "agents": [
            {
                "name": "drv",
                "mode": "active",
                "interface": {"signals": [{"name": "req", "width": 1}]},
                "transaction": {"fields": []},
            }
        ],
        "sequences": [{"name": "smoke", "agent": "drv"}],
        "tests": [{"name": "t", "seqs": ["smoke"]}],
    }
    spec_path = wd.parent / "scaffold-specification.json"  # any readable path
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec))
    r = _run(main, module, wd, "--scaffold", str(spec_path))
    assert r.returncode == 0, r.stderr
    # interface files are named by module ({module}_{agent}_if.sv), not by top
    assert (wd / f"tb/uvm/interface/{module}_drv_if.sv").is_file()


def test_bootstrap_aborts_on_existing_makefile(tmp_path):
    main, wd, module = _mirror(tmp_path)
    wd.mkdir(parents=True)
    (wd / "Makefile").write_text("# pre-existing\n")
    r = _run(main, module, wd)
    assert r.returncode == 1 and "already deployed" in r.stderr


def test_bootstrap_allows_hint_only_workdir(tmp_path):
    main, wd, module = _mirror(tmp_path)
    wd.mkdir(parents=True)
    (wd / "orchestrator-context.md").write_text("hints\n")  # not a Makefile
    r = _run(main, module, wd)
    assert r.returncode == 0, r.stderr
    assert (wd / "Makefile").is_file()


def test_bootstrap_uninferrable_top_exit_1(tmp_path):
    main, wd, module = _mirror(
        tmp_path,
        readme="no top here\n",
        filelist="+incdir+inc\n",
        manifest={"children": []},  # no module -> manifest can't infer either
    )
    r = _run(main, module, wd)
    assert r.returncode == 1 and "infer top" in r.stderr.lower()


def test_bootstrap_missing_rtl_filelist_exit_1(tmp_path):
    main, wd, module = _mirror(tmp_path)
    (tmp_path / "asic" / module / "Design" / "rtl-design" / "filelist.txt").unlink()
    r = _run(main, module, wd, "--top", "dut")
    assert r.returncode == 1 and "RTL filelist" in r.stderr


def test_bootstrap_missing_scaffold_file_exit_1(tmp_path):
    main, wd, module = _mirror(tmp_path)
    r = _run(main, module, wd, "--scaffold", str(tmp_path / "nope.json"))
    assert r.returncode == 1 and "scaffold-specification.json" in r.stderr


def test_bootstrap_chmods_scripts(tmp_path):
    import os

    main, wd, module = _mirror(tmp_path)
    _run(main, module, wd)
    for sh in (wd / "scripts").glob("*.sh"):
        assert os.access(sh, os.X_OK)
