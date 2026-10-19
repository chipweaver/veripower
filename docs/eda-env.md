# EDA Tool Environment

[中文版](eda-env.zh.md)

Use this guide to prepare tools and resources for your design task, check that
they work in the agent's execution environment, and diagnose environment
failures. It describes the tool interfaces used by the supplied VeriPower stages.
Select tool releases, libraries, models and analysis conditions to suit the
hardware task and your available installation.

## 1. Establish the execution environment

Stage scripts launch tools as the calling user. The executing processes need
access to the workspace, source files, libraries and model files, and permission
to write their outputs. Tool-produced executables, such as a VCS `simv`, also
need a compatible runtime environment.

Load the tool setup where the agent's commands will run. If you use a shell
script for this setup, source it before launching an agent harness such as
Claude Code, OpenCode, DeepSeek Harness or Codex from the same environment.
Replace the illustrative path below with your actual setup script:

```bash
. "/path/to/site-eda-setup.sh"
```

This setup should make the needed commands available through `PATH`, load
the site's license settings, and provide access to the selected resources.
Synopsys installations commonly use `SNPSLMD_LICENSE_FILE` or `LM_LICENSE_FILE`.
Use the values from your existing license configuration or license administrator.

Check the environment through the agent's execution tools. A command working in
your interactive terminal does not establish that a separately launched process
has the same setup. Exported variables are inherited by child processes, and
Bash's startup files depend on how it is invoked; `~/.bashrc` alone is not a
universal entry point. See the Bash documentation on
[environment inheritance](https://www.gnu.org/software/bash/manual/html_node/Environment.html)
and [startup files](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html).

If your site uses containers, remote execution or tool wrappers, check paths,
permissions, license access and output visibility where the tools actually
run. Such integration must preserve the stage's command interface, wait for
tool completion and return its exit status and outputs.

## 2. Prepare tools for the intended work

Install the Python dependencies in [requirements.txt](../requirements.txt) in
the environment used by the stage scripts. The table identifies the additional
capabilities needed for each kind of work. Ensure that the available licenses
cover the features used by the work; successful tool startup alone is insufficient.

| Work | Required tools or capabilities |
|---|---|
| Shared scripts | `python3` 3.10 or later, with the declared Python dependencies |
| Supplied shell and build scripts | Bash; `make` for lint/CDC and simulation |
| RTL compilation | A compiler supporting the task's RTL language, source list and include paths; the RTL stage must compile the complete file set |
| Functional simulation | `vcs`, UVM sources through `UVM_HOME`, and a C/C++ toolchain compatible with that VCS release |
| Structural coverage | VCS coverage instrumentation and `urg` reporting for the required metrics |
| Waveform capture and diagnosis | VCS/Verdi FSDB support for the supplied simulation runner; `fsdbreport` for waveform queries, and `fsdb2vcd` when conversion is used |
| Lint and CDC | `spyglass` with the lint and CDC goals used by the stage |
| Synthesis | `dc_shell` with the DC-Ultra capability used by `compile_ultra` |
| Static timing analysis | `pt_shell` with the required timing-analysis features |
| Power experiments and calculation | The experiment's simulator, cell models and any additional workload dependencies; `pt_shell` with the PrimeTime-PX power-analysis capability for calculation |

Specification and verification planning use the shared Python dependencies.
RTL design also requires compilation. A power recalculation using applicable
existing activity data needs the calculation environment; compiling and running
a new experiment additionally needs its simulation environment.

For UVM simulation, `UVM_HOME` must identify the distribution whose
`src/uvm_pkg.sv` and `src/dpi/uvm_dpi.cc` are used by the build. The supplied
runner accepts optional `VCS_CC` and `VCS_CPP` settings to select the C and C++
compilers through VCS's `-cc` and `-cpp` options. Choose versions supported by
your installed tool release.

## 3. Provide libraries, models and stage settings

Provide the stage executor with the library and model locations, their intended
use, and the analysis conditions required by the task. This can include libraries
and simulation models for standard cells, memories or other macros, together
with operating conditions and the chosen interconnect estimate. Use the design
requirements and the library or model provider's documentation to identify
suitable resources and conditions. Libraries used to link and analyze a netlist
must cover the cells it contains; simulation models must match that implementation.

Keep site resource locations distinct from task decisions such as the selected
library operating conditions or wire-load model. The executor records the
effective settings in the stage workdir. The current entry points are:

| Work | Where the supplied stage takes its settings |
|---|---|
| Synthesis | `config.tcl` supplies `LIB_DB` and `WIRE_LOAD_MODEL`. Bootstrap initializes these from the environment only when this file does not exist. |
| Timing analysis | `config.tcl` supplies `LIB_DB`, along with the top and netlist location established from the stage inputs. Bootstrap uses the environment's library setting only when creating the file. |
| Power calculation | Source the workdir's `env.sh` before invoking the stage CLI. `LIB_DB` is a Tcl list of linked library paths; `STRIP_PATH` identifies the captured DUT hierarchy in the SAIF data. |
| Simulation and power experiments | Simulation's `env.sh` provides `UVM_HOME` and run settings. The authored power experiment's compile/run scripts provide its simulator, model files and workload setup. |

Changing an exported value does not update an existing `config.tcl`. Inspect
the effective stage configuration when reusing a workdir or changing resources.

The supplied synthesis and timing templates configure `LIB_DB` as a single
`.db` path. Tasks needing additional link libraries, macros or operating-condition
setup require corresponding changes to the stage's tool configuration. Exporting
a list alone does not change these templates. The power template already reads
`LIB_DB` as a Tcl list. For example, after replacing each path with the actual
library, a power calculation can use:

```bash
export LIB_DB='{/path/to/cell-library.db} {/path/to/macro-library.db}'
```

Include only the libraries needed by that calculation. For synthesis,
`WIRE_LOAD_MODEL` is a model present in the selected library or the explicit
value `none`, chosen for the task's intended interconnect estimate.

`LIB_V` can identify an available cell-model resource, but the power CLI does
not automatically add it to a simulator file list. The experiment's build must
include the actual cell and macro models it needs. Check model completeness and
measurement conditions against the task requirements.

Stage-specific setup is described in the
[synthesis](../skills/synthesis/SKILL.md),
[timing-analysis](../skills/timing-analysis/SKILL.md) and
[power-analysis](../skills/power-analysis/SKILL.md) skills.

## 4. Check readiness

In a separate session with VeriPower enabled, ask:

> Run the env-precheck skill for the work I intend to perform. Check from the execution environment used by the stages, and report what can run, what failed and what was not tested.

State the stages or calculations you intend to run and provide the selected
resource locations. The check first probes tools and settings, then runs small
jobs in temporary directories to exercise the relevant licenses and execution
paths. Probes need timeouts so an unavailable license service cannot leave a
check waiting indefinitely.

Read the report for the actual work performed and the outputs produced: for
example, a mapped netlist, a timing report, simulation output, a coverage report
or a power report. A version banner, a listed license feature or a zero exit code
alone does not establish readiness. The
[env-precheck skill](../skills/env-precheck/SKILL.md) defines the checks.

Resolve missing prerequisites and repeat the affected checks. A skipped or
untested item remains unverified. Recheck affected capabilities after changing
tool versions, resource locations or execution environments, and have the agent
reassess affected measurements from earlier work. Prechecks establish readiness
for the tested setup; the actual task and its results still require assessment
by the responsible stages. The precheck reports findings and suggested
environment settings without changing your shell configuration or module files.

## 5. Diagnose environment failures

Use the command, execution location, tool version and log from the failed work
to identify the cause.

| Symptom | What to check next |
|---|---|
| Command not found, or different behavior inside the agent | Check `PATH`, the selected Python environment and the setup loaded by the actual execution process. |
| License checkout fails or waits indefinitely | Check the site's license settings, server reachability and entitlement for the requested feature. Repeat a bounded check that exercises that feature. |
| Tool launcher fails before reading the design | Check the installed launcher's interpreter and the release's supported operating environment. Apply the site's supported setup; a system-wide `/bin/sh` change is not a universal VeriPower prerequisite. |
| VCS fails during C/C++ compilation or linking | Check the compiler and linker compatibility for that VCS release. Set `VCS_CC` and `VCS_CPP` when explicit compiler selection is needed. |
| Library, cell or model cannot be found | Check file visibility, the effective `config.tcl` or `env.sh`, and whether the linked libraries and simulation file list cover the actual design. |
| Tools finish but coverage or power reports are unusable | Check the report-generation options, instrumentation and analysis scope before interpreting the result. Inspect the stage's raw reports and logs. |

For structural coverage, the supplied runner requests `urg -format text` and
passes its report directory to the parser through `--cov-dir`. The parser needs
`dashboard.txt` and `modinfo.txt`. Check that the requested metrics were enabled
during compilation and that the configured DUT instance matches the design.
An unsupported report layout or an absent measurement cannot satisfy a coverage
target. Parser details are in
[parse_coverage.py](../skills/simulation/templates/infra/scripts/parse_coverage.py).

For power, check that the selected netlist, libraries and constraints match the
experiment, that the SAIF covers the intended activity and measurement interval,
and that `STRIP_PATH` matches the captured hierarchy. A numeric report alone does
not establish a valid measurement.

For starting, reviewing or resuming a design task, see the
[User Guide](USER-MANUAL.md).
