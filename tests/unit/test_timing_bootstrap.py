# tests/unit/test_timing_bootstrap.py
"""timing bootstrap — deploy-into-workdir behavior.

Two layers: in-process unit tests of infer_top, and subprocess "mirror"
tests of full deploy behavior that run the real shipped skill with cwd
set to a tmp design-tree root and build the synthesis output tree (netlist + SDC)
under it. The
bootstrap anchors the design tree on the CWD (matching kernel.py and the
stage-subagent contract), independent of where the skill code lives.

`make_tree` pre-populates workdir/dispatch.json (the single netlist key) the way
kernel.py dispatch injects it at dispatch time — bootstrap reads the upstream
synthesis-stage-root location from dispatch.json instead of self-navigating
tree_root/asic/<module>/Design/synthesis.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "skills" / "timing-analysis" / "scripts" / "timing" / "__main__.py"
sys.path.insert(0, str(REPO_ROOT / "skills" / "timing-analysis" / "scripts"))
from timing import bootstrap  # noqa: E402


# ── infer_top (in-process, precise) ───────────────────────────────────────────
def test_infer_top_single_match(tmp_path):
    out = tmp_path / "Design" / "synthesis" / "out"
    out.mkdir(parents=True)
    (out / "packet_engine_syn.v").write_text("// netlist\n")
    assert bootstrap.infer_top(tmp_path / "Design" / "synthesis") == "packet_engine"


def test_infer_top_none_when_absent(tmp_path):
    (tmp_path / "Design" / "synthesis" / "out").mkdir(parents=True)
    assert bootstrap.infer_top(tmp_path / "Design" / "synthesis") is None


def test_infer_top_none_when_multiple(tmp_path):
    out = tmp_path / "Design" / "synthesis" / "out"
    out.mkdir(parents=True)
    (out / "a_syn.v").write_text("x")
    (out / "b_syn.v").write_text("x")
    assert bootstrap.infer_top(tmp_path / "Design" / "synthesis") is None


# ── full deploy (subprocess mirror) ───────────────────────────────────────────
def make_tree(
    tmp_path,
    *,
    top="packet_engine",
    with_netlist=True,
    with_sdc=True,
):
    """Build a synthesis output tree (netlist + SDC) under a tmp design-tree root,
    and pre-populate workdir/dispatch.json (the single netlist key) the way kernel.py
    dispatch injects it at dispatch time.

    Returns (module, workdir, main). Deploy tests run `main` (the real shipped skill)
    with cwd=tmp_path, so the bootstrap anchors the design tree on the CWD.
    """
    m = top
    syn = tmp_path / "asic" / m / "Design" / "synthesis"
    (syn / "out").mkdir(parents=True)
    if with_netlist:
        (syn / "out" / f"{top}_syn.v").write_text("// netlist\n")
    if with_sdc:
        (syn / "out" / f"{top}_syn.sdc").write_text("# sdc\n")
    workdir = tmp_path / "asic" / m / "Design" / "timing-analysis" / "runs" / "1"
    workdir.mkdir(parents=True)
    (workdir / "dispatch.json").write_text(
        json.dumps({"inputs": {"netlist": str(syn)}})
    )
    return m, workdir, MAIN


# A real file: bootstrap refuses a LIB_DB path that is not there, because env.sh is
# the record of which library the STA linked against. Created once for the module.
LIB_DB = str(Path(tempfile.mkdtemp(prefix="timing-lib-")) / "slow.db")
Path(LIB_DB).write_text("# stand-in for a .db\n")


def run(workdir, main, extra=None, cwd=None, lib_db=LIB_DB):
    """Run the bootstrap verb. `lib_db=None` runs it with LIB_DB out of the
    environment; the default supplies one so deploy tests reach the deploy."""
    if cwd is None:
        # The bootstrap anchors the design tree on the CWD; the tree root is the
        # prefix of the (absolute) workdir up to the 'asic/' component.
        parts = Path(workdir).parts
        cwd = Path(*parts[: parts.index("asic")])
    cmd = [
        "python3",
        str(main),
        "bootstrap",
        "--workdir",
        str(workdir),
    ]
    if extra:
        cmd += extra
    env = {k: v for k, v in os.environ.items() if k != "LIB_DB"}
    if lib_db is not None:
        env["LIB_DB"] = lib_db
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)


def test_deploys_and_substitutes(tmp_path):
    m, workdir, main = make_tree(tmp_path)
    r = run(workdir, main)
    assert r.returncode == 0, r.stderr
    tcl = (workdir / "run_sta.tcl").read_text()
    assert (
        "asic/packet_engine" in (workdir / "config.tcl").read_text()
    )  # NETLIST_DIR substituted (abs, contains asic/<m>)
    assert (
        "MY_MODULE" not in tcl and "MY_NETLIST" not in tcl and "MY_WORKDIR" not in tcl
    )
    cfg = (workdir / "config.tcl").read_text()
    assert 'set TOP "packet_engine"' in cfg  # MY_TOP substituted
    assert "MY_TOP" not in cfg


def test_workdir_and_netlist_dir_are_absolute(tmp_path):
    m, workdir, main = make_tree(tmp_path)
    assert run(workdir, main).returncode == 0
    tcl = (workdir / "run_sta.tcl").read_text()
    # pt_shell runs from the workdir; NETLIST_DIR/WORKDIR are absolute so reads resolve
    # from any CWD and PT's auto-logs land inside the gitignored workdir.
    assert "set WORKDIR [pwd]" in tcl
    # module root is a path-prefix of the (absolute) synthesis stage root NETLIST_DIR
    assert str(tmp_path / "asic" / m) in (workdir / "config.tcl").read_text()
    assert "set WORKDIR     asic/" not in tcl  # the old tree-root-relative form is gone


def test_run_sta_reads_absolute_netlist_from_dispatch_json(tmp_path):
    # Bootstrap reads the upstream synthesis-stage-root location from the injected
    # dispatch.json "netlist" key — not by self-navigating
    # tree_root/asic/<module>/Design/synthesis. run_sta.tcl must bake the ABSOLUTE
    # netlist dir (NETLIST_DIR), never a MY_MODULE_ROOT placeholder or a baked
    # "Design/synthesis" self-nav path. $WORKDIR (a same-stage self-ref) must
    # survive.
    m, workdir, main = make_tree(tmp_path)
    synth_root = tmp_path / "asic" / m / "Design" / "synthesis"
    r = run(workdir, main)
    assert r.returncode == 0, r.stderr
    sta = (workdir / "run_sta.tcl").read_text()
    assert str(synth_root) in (workdir / "config.tcl").read_text()
    assert (
        "MY_MODULE_ROOT" not in sta
        and "MY_NETLIST_DIR" not in sta
        and "$MODULE_ROOT/Design/synthesis" not in sta
    )
    assert "set WORKDIR" in sta  # same-stage $WORKDIR self-ref must survive


def test_setup_does_not_require_the_execution_library(tmp_path):
    unused, workdir, main = make_tree(tmp_path)
    assert run(workdir, main, lib_db=None).returncode == 0
    assert "set LIB_DB" not in (workdir / "config.tcl").read_text()
    probe = subprocess.run(
        ["tclsh", "run_sta.tcl"], cwd=workdir, capture_output=True, text=True
    )
    assert probe.returncode == 1 and "LIB_DB" in probe.stderr
    assert (
        "source [file join [pwd] config.tcl]" in (workdir / "run_sta.tcl").read_text()
    )


def test_fail_closed_when_netlist_missing(tmp_path):
    # Pass --top so we get past TOP-inference and hit the netlist-existence check.
    m, workdir, main = make_tree(tmp_path, with_netlist=False)
    r = run(workdir, main, extra=["--top", "packet_engine"])
    assert r.returncode == 1
    assert "external reference" in r.stderr
    assert not (workdir / "run_sta.tcl").exists()


def test_fail_closed_when_sdc_missing(tmp_path):
    # This is two-sided: the netlist alone is not enough; PT also reads the SDC.
    m, workdir, main = make_tree(tmp_path, with_sdc=False)
    r = run(workdir, main, extra=["--top", "packet_engine"])
    assert r.returncode == 1
    assert "external reference" in r.stderr
    assert not (workdir / "run_sta.tcl").exists()


def test_cant_infer_top_no_netlist(tmp_path):
    # No --top and no out/*_syn.v -> inference returns None -> fail-closed exit 1.
    m, workdir, main = make_tree(tmp_path, with_netlist=False)
    r = run(workdir, main)  # no --top
    assert r.returncode == 1
    assert "cannot infer top" in r.stderr


def test_cant_infer_top_multiple(tmp_path):
    # Two out/*_syn.v -> inference is ambiguous -> fail-closed exit 1.
    m, workdir, main = make_tree(tmp_path)
    syn_out = tmp_path / "asic" / m / "Design" / "synthesis" / "out"
    (syn_out / "other_syn.v").write_text("// second netlist\n")
    r = run(workdir, main)  # no --top
    assert r.returncode == 1
    assert "cannot infer top" in r.stderr


def test_bootstrap_preserves_authored_analysis(tmp_path):
    unused, workdir, main = make_tree(tmp_path)
    assert run(workdir, main).returncode == 0
    (workdir / "run_sta.tcl").write_text("# authored analysis\n")
    assert run(workdir, main).returncode == 0
    assert (workdir / "run_sta.tcl").read_text() == "# authored analysis\n"


def test_missing_template_dir_fail_closed(tmp_path):
    # Run a skill COPY whose templates/ has been removed -> fail-closed before any
    # mutation. The synthesis prereq tree itself is valid under the CWD.
    m, workdir, unused = make_tree(tmp_path)
    skill_copy = tmp_path / "skills" / "timing-analysis"
    shutil.copytree(REPO_ROOT / "skills" / "timing-analysis", skill_copy)
    shutil.rmtree(skill_copy / "templates")
    main = skill_copy / "scripts" / "timing" / "__main__.py"
    r = run(workdir, main, extra=["--top", "packet_engine"])
    assert r.returncode == 1
    assert "missing" in r.stderr
    assert not (workdir / "run_sta.tcl").exists()


def test_relative_workdir_with_trailing_slash(tmp_path):
    # A relative --workdir resolves against the CWD (the design-tree root), and
    # the trailing slash is dropped (type=Path) before deploy.
    m, workdir, main = make_tree(tmp_path)
    # Through run, so this inherits the same hermetic environment as every other
    # deploy test rather than whatever LIB_DB the caller's shell happens to export.
    proc = run(
        "asic/packet_engine/Design/timing-analysis/runs/1/",  # relative + trailing slash
        main,
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert (workdir / "run_sta.tcl").is_file()  # resolved to the absolute location
    assert (workdir / "config.tcl").is_file()


def test_library_path_remains_one_tcl_argument(tmp_path):
    unused, workdir, main = make_tree(tmp_path)
    library = tmp_path / "cell library.db"
    library.write_text("library input")
    assert run(workdir, main, lib_db=str(library)).returncode == 0
    (workdir / "probe.tcl").write_text("""proc read_verilog args {return 1}
proc link_design args {
    if {[llength $::target_library] != 1 || [llength $::link_library] != 2} {exit 3}
    if {[lindex $::target_library 0] ne $::LIB_DB} {exit 4}
    exit 0
}
source run_sta.tcl
""")
    probe = subprocess.run(
        ["tclsh", "probe.tcl"], cwd=workdir, capture_output=True, text=True
    )
    assert probe.returncode == 0, probe.stderr
