# VeriPower Architecture

[中文版](ARCHITECTURE.zh.md)

VeriPower consists of a workflow engine, stage skills, and integration with a
coding agent harness. This document describes their boundaries, the data they
share, and the rules that govern execution. Setup and usage are covered in the
[user manual](docs/USER-MANUAL.md).

## 1. System boundary

The host harness provides the model, conversation context, file access, command
execution, and subagents. VeriPower provides the design and verification tasks
and the machinery that coordinates them. EDA tools run as external programs
and produce files that the stages inspect and publish.

<p align="center">
  <a href="assets/plugin-architecture.png">
    <img src="assets/plugin-architecture.png" alt="VeriPower and its host, EDA tools, and engineer" width="600" />
  </a>
  <br>
  <sub><a href="assets/plugin-architecture.png">System context · View full size</a></sub>
</p>

There are three roles within the flow.

| Role | Responsibility |
|---|---|
| Stage executor | Develop artifacts, run checks, interpret evidence, and report a verdict or repair recommendation |
| Workflow engine | Record runs, evaluate result validity, and select work using dependencies and outstanding failures |
| Orchestrator | Carry out the engine's actions through host tools and manage executor completion |

The orchestrator is the agent following the `design-flow` skill. Stage work
runs either in the main conversation or in a background subagent, according
to the stage declaration.

This division places engineering judgment with the work that produces its
evidence. Cross-stage decisions use a common representation of dependencies,
runs, and artifact versions. The host retains control of tool permissions.
Engineers supply requirements and determine which decisions to delegate.

## 2. Component design

The engine exposes a CLI through `kernel.py`. Each call reads the module's
records and files, performs the requested operation, and returns a structured
response. The orchestrator uses this interface to coordinate the flow.

<p align="center">
  <a href="assets/implementation-architecture.png">
    <img src="assets/implementation-architecture.png" alt="Workflow engine modules and their connections to stage skills and schemas" width="600" />
  </a>
  <br>
  <sub><a href="assets/implementation-architecture.png">Implementation structure · View full size</a></sub>
</p>

| Component | Responsibility |
|---|---|
| [rules.py](framework/scripts/rules.py) | Stage declarations and the artifact graph derived from their inputs |
| [facts.py](framework/scripts/facts.py) | Read-only queries for fingerprints, result validity, stage status, and acceptance readiness |
| [schedule.py](framework/scripts/schedule.py) | Selection of the next action from current facts and unresolved repairs |
| [store.py](framework/scripts/store.py) | Event storage, schema validation, task handoff, and artifact publication |
| [kernel.py](framework/scripts/kernel.py) | CLI operations that coordinate these components |

A stage package under `skills/<stage>/` contains its instructions, scripts,
and result schema. Tool invocation, report parsing, and stage checks belong
there. The shared engine handles the lifecycle of the result, while the stage
package determines its technical meaning.

Each stage schema extends the shared
[result envelope](framework/references/schemas/envelope.schema.json). The
common fields identify the stage, production time, pass/fail verdict, artifact
list, and stage-specific evidence. This interface lets stages use different
tools and checking methods while participating in the same workflow.

The `design-flow` skill connects the engine to the host's execution facilities.
Platform integration supplies the corresponding tool calls. Stage definitions
and result semantics remain in the shared engine and stage packages.

## 3. Project data model

### Stages and artifact ownership

One module directory is the workspace for one design flow. It contains the
original intent, published stage artifacts, run directories, and event history.

```text
module/
├── intent/                 Original requirements and supporting material
├── events.jsonl            Execution and decision history
├── Design/<stage>/         Published design-stage artifacts
│   └── runs/<run>/          Work for a numbered execution
└── Verification/<stage>/   Published verification-stage artifacts
    └── runs/<run>/          Work for a numbered execution
```

A stage declaration names its skill, execution mode, directory root, and input
selectors. Published directories have distinct owners. Inputs select files or
directory trees, and their paths identify the producing stage. Consumers use
these artifacts as read-only inputs. Changes belong to the producing stage.

These declarations form the dependency graph. Simulation, for example, uses
RTL from `rtl-design`, verification artifacts from `simulation-plan`, and
boundary declarations and requirements from `specification`. Its execution
and repair dependencies follow those relationships.

The registry contains eight stages with required conclusions, covering
specification through power analysis. `simulation-triage` is an additional
diagnostic task whose output is a diagnosis. `brainstorm` and `env-precheck`
prepare requirements and check the environment before the flow starts.
The [README](README.md#design-flow) shows the complete stage overview.

### Runs, results, and events

A run is identified by its stage and run number. The engine creates a work
directory and writes `dispatch.json` with input locations and repair context.
For stages that produce conclusions, the dispatch event also records input
fingerprints. Reusable products are carried into the new work directory
according to the stage declaration.

The stage CLI writes `result.json`. On collection, the engine validates its
schema and timestamp, publishes the listed artifacts, and appends an `outcome`
event containing the verdict, output fingerprints, and reported requirement
judgments. Passing and failing runs both publish evidence. A missing,
unreadable, or invalid result envelope is collected as `blocked` without
replacing the published artifacts.

Published files are hard-linked from the run directory. The two paths share
file content, while fingerprints in the event log preserve the version
identifiers recorded at collection. The log is append-only, and the engine
validates each event before writing it.

### Current conclusions

The implementation calls a stage conclusion a **proof**. Its verdict and
input fingerprints, together with the `outcome` event's output fingerprints, bind it
to the artifacts from one run.

Only the stage's latest collected outcome supplies its current conclusion.
A pass remains valid when all recorded inputs and outputs are readable and
still match their fingerprints. A later failure or blocked outcome replaces
an earlier pass. If the latest outcome is a pass, restoring the recorded file
versions can restore validity without another run.

This rule covers changes to both dependencies and a stage's own outputs. A
testbench edit affects simulation and power analysis that consumed it, while
lint/CDC can remain valid. An RTL edit affects RTL design, lint/CDC, synthesis,
and simulation. Timing and power results are subsequently checked against the
netlist and other inputs they recorded.

Stage status is derived from the event log and current files on each query.

| Status | Meaning |
|---|---|
| `missing` | No outcome has been collected |
| `in-flight` | A dispatched run has no outcome yet |
| `blocked` | The latest collection could not establish a pass/fail result |
| `failed` | The latest outcome is a failure |
| `valid` | The latest outcome passes and its recorded versions match |
| `stale` | The latest outcome passes but its recorded versions no longer match |

An uncollected run takes precedence over the stage's previous outcome when
status is displayed. Executor exit alone does not close the run. The
orchestrator reports that exit and collects the result, including a missing
result. After a session interruption, the same records identify outstanding
runs and the results available for reuse.

### Versioning boundary

Files use content hashes, and directory fingerprints cover their paths and
contents. Every stage proof includes the whole `intent/` tree, including
`brainstorm.md` and the material supplied with it.

The tracked set consists of declared inputs and recorded outputs. An extra
file read by an agent does not automatically enter that set. Symbolic links
are fingerprinted by their target paths without following the target content.
Tool and library identifiers are recorded for audit rather than used in result
validity checks. These distinctions determine which changes the engine can
recognize from its records.

## 4. Execution and rework

The engine returns one action at a time. The orchestrator executes it and
queries again as work completes or new evidence becomes available.

| Action | Orchestrator's work |
|---|---|
| `DISPATCH` | Ask the engine to prepare a run, then execute the assigned stage skill |
| `REAP` | Confirm executor exit and collect the run's result through the engine |
| `YIELD` | Wait for outstanding executors |
| `ESCALATE` | Resolve the reported blocker under the task's authorization |
| `DONE` | Finish the requested flow |

The scheduler first selects results ready for collection. It then handles
unresolved attribution, schedules repairs and ready stages, or waits for work
already running. The engine derives the next action from the records and
current files, so the orchestrator does not need to maintain a second model
of stage status.

### Dependency rules

A design or verification stage requires available inputs and current passing
results from their producers. A running producer or consumer prevents work
that would conflict with it. Pending upstream repairs are handled before the
affected checks run again. Independent stages can execute concurrently,
including lint/CDC and simulation reading the same RTL.

The registry also declares advisory ordering for lint/CDC before synthesis
and timing analysis before power analysis. These preferences apply when the
predecessor needs work and is scheduled or running. They affect scheduling,
while artifact dependencies define result validity and repair scope.

### Repair routing

The failing stage can report a `fix_owner`. The owner must be that stage
itself or an upstream producer in its dependency graph. This ties repair
scope to artifact ownership. The agent establishes the technical cause,
and the engine checks whether the proposed owner is within that scope.

Simulation failures without an identified owner trigger `simulation-triage`.
It investigates the failed run and records diagnoses. A diagnosis can explicitly
supersede an earlier one, and active diagnoses take precedence over the stage's
original attribution. An unresolved or unrelated attribution requires a
decision before scheduling continues.

Failures assigned to the same owner are grouped into one repair run. The run
receives the relevant results and diagnoses as context. Once repaired artifacts
are published, the engine recomputes validity and schedules the checks that
need to be repeated.

## 5. Engineering judgments and acceptance

### Meaning of a stage verdict

A stage's passing criteria are defined by its skill and scripts. Scripts check
artifact structure, execution results, and numerical targets. Agents review
design choices, checking logic, and tool findings against the requirements.
The stage CLI records the resulting verdict and evidence in the common result
format. The engine checks that format and the versions it refers to.

The specification stage creates a requirements ledger with stable identifiers,
source wording, judgment responsibility, and numerical targets where applicable.
Stages use these identifiers to relate design choices, testpoints, measurements,
and verdicts to the original requirements. Numerical verdicts record measured
values and their source.

RTL and verification share the specification's interface, clock, and reset
declarations. Verification plans and reference models derive expected behavior
from the specification and independent references. Simulation may inspect RTL
to diagnose failures. Independent reviews examine whether the stimulus,
observations, and checking logic can detect violations of the testpoints.

The ledger also records decisions, external responsibilities, and context.
Unresolved requirements marked `unassignable` prevent specification from
passing. Requirements assigned `outside` retain a named responsibility beyond
the design flow.

### Completion and acceptance records

The flow completes when all required stages have current passing results and
all dispatched runs have been collected. The closing check additionally
requires the published files to be covered by stage output records and returns
the evidence for acceptance. Run history under `runs/` is excluded from this
published-file check. The CLI exposes this check through `decide --closing`.

When the task includes recorded acceptance, `signoff` applies the validity and
artifact checks and appends a decision with `provenance` and `reason`. These
identify the decision maker, authorization, and acceptance basis. Reserved
decisions remain with the engineer, while delegated decisions follow existing
authorization. Ordinary completion does not require a separate signoff.

The acceptance record binds the stage evidence present at that event. Changes
that invalidate those results also invalidate acceptance. Restoring the same
evidence can restore validity, while a new stage run requires acceptance of
its new result.

For shared interface definitions, see the [framework guide](framework/README.md).
Development guidance is in [Contributing](CONTRIBUTING.md).
