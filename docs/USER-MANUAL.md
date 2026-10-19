# VeriPower User Guide

[中文版](USER-MANUAL.zh.md)

This guide is for engineers using a coding agent for chip front-end development.
It covers preparing a task, running the flow, reviewing results and continuing
after changes or interruptions. In the prompts below, replace `{module_dir}`
with the absolute path to your module workspace: the
directory containing its requirements, generated artifacts and run history.

## 1. Prepare the environment

Choose an agent harness, such as Claude Code, OpenCode, DeepSeek Harness or Codex,
and follow its installation guide:

[Claude Code](../.claude/README.md) · [OpenCode](../.opencode/README.md) ·
[DeepSeek Harness](../.dsh/README.md) · [Codex](../.codex-plugin/README.md)

These guides cover installation, enablement, updates and platform-specific
settings. Start a session with the plugin enabled and ask the agent to list its
VeriPower skills to check that it loaded.

The flow's scripts require Python 3.10 or later and the packages in
[requirements.txt](../requirements.txt), installed in the Python environment
available to the agent. From a source checkout, install them with:

```bash
python3 -m pip install -r requirements.txt
```

The supplied full flow uses Synopsys SpyGlass, VCS with UVM, Verdi waveform tools,
Design Compiler and PrimeTime for timing and power analysis. Provide the tools,
licenses and cell libraries, and make their configuration available in the
environment used to launch the agent harness. See
[EDA Tool Environment](eda-env.md) for the required settings and tool-specific
troubleshooting.

To check readiness, use a separate session and ask:

> Run the env-precheck skill for all stages of the VeriPower flow.

The check probes tool availability and runs small license and execution checks.
It reports which stages can run and what needs attention. Resolve missing
prerequisites before running the affected work. You can prepare requirements
while configuring the tools; completing implementation checks and the full flow
requires the corresponding tools to be available.

## 2. Define the task

Choose a module workspace and put the original requirements and reference
material under `intent/`:

```text
module_dir/
└── intent/
    ├── brainstorm.md
    └── ...                 Reference models, register maps or other reference materials
```

The input filename `intent/brainstorm.md` is fixed. You can place an existing
specification there using its own format. Include:

- Required behavior, interfaces, clocks and resets.
- Timing, area, power and coverage targets, with units and applicable conditions.
- The role of each reference, including any existing RTL or tests.
- Open design choices, decisions you delegate, and targets intentionally left unconstrained.

Copy the reference files into `intent/` and cite them from the requirements.
Files elsewhere are not automatically included as original input. A symbolic
link does not track changes to its target's contents, so copy authoritative
material rather than relying on a link to an external file.

If you need help establishing the requirements, use the `brainstorm` skill in a
separate session:

> Run the brainstorm skill for {module_dir}. Use the supplied requirements and references to establish the design task.

Review the resulting `intent/brainstorm.md` and its referenced material before
starting the flow. An existing suitable specification can be used directly;
`brainstorm` is one way to prepare it. Existing RTL and tests can be supplied as
references, but placing them in the workspace does not register completed stages.

## 3. Run and follow the work

Start a new session with VeriPower enabled and ask:

> Run the design-flow skill for {module_dir}.

The agent develops the specification and RTL, plans and implements verification,
and coordinates tool analyses and rework. State any decisions you reserve and
whether the task requires a recorded acceptance. The agent can proceed within your
existing authorization and brings back questions that need your input. Tool
execution remains subject to the agent harness's permissions.

To check progress, ask:

> Report the current status of {module_dir}, including unfinished work, failed checks and any decision needed from me.

The status view uses these labels:

| Status | Meaning and next step |
|---|---|
| `missing` | No result has been collected yet; the flow schedules the required work. |
| `in-flight` | A dispatched run has not been collected. The agent confirms executor exit before collecting its result. |
| `valid` | The latest result passes and still matches the recorded files. |
| `stale` | A recorded input or output changed after a pass; the affected work needs reassessment. |
| `failed` | The latest stage assessment failed; the agent investigates the cause and arranges repair. |
| `blocked` | Collection could not obtain a usable stage result; the agent must resolve the reported cause. |

If work stops, ask for the affected stage, the relevant evidence and the proposed
next action. For missing tools or licenses, use the environment guide and
`env-precheck`. For a design or verification finding, provide any requested
requirements clarification and let the agent investigate and repair it.
A failed check alone does not identify which artifact needs changing.

## 4. Review and save results

You can review published results as work progresses. Ask for a summary tied to
the original requirements:

> Summarize the results for {module_dir} against the original requirements. Include the verdict and technical evidence for each requirement, measurement conditions, unresolved findings and any requirements that need assessment outside the flow.

Start with the files below. Directories are relative to `{module_dir}`; filenames
are relative to the directory in their row. Each stage's `result.json` records
its verdict and the artifacts actually published.

| Review area | Directory | Files to start with |
|---|---|---|
| Design description and requirements ledger | `Design/specification/` | `design.md`, `requirements.json` |
| Verification planning | `Verification/simulation-plan/` | `verification-plan.md` |
| RTL implementation | `Design/rtl-design/` | `src/`, `rtl-files.json` |
| Functional simulation | `Verification/simulation/` | `case-results-summary.md`, `structural-coverage.json`, `check-review.md` |
| Lint / CDC | `Design/lint-cdc/` | `lint-report.txt`, `cdc-report.txt` |
| Logic synthesis | `Design/synthesis/` | `out/`, `reports/` |
| Timing analysis | `Design/timing-analysis/` | `timing-report.txt` |
| Power analysis | `Verification/power-analysis/` | `analysis.md`, `reports_ptpx/` |

Use the requirement identifiers in the ledger to trace design decisions,
testpoints and stage verdicts back to the original requirements. Check that
requirements have not been omitted or weakened. Then check the following:

- Compare the test plan with actual execution results and identify
  requirements that remain unchecked. Expected behavior should be derived from
  requirements and independent reference materials.
- Check units, conditions and analysis scope. Power results are
  averages over the measurement interval for the executed scenarios.
- Review the grounds for waivers, unresolved findings and
  requirements whose assessment is assigned outside the flow.

### Completion and acceptance

The flow completes when every required stage has a passing result applicable to
the current artifacts and all dispatched runs have been collected. Ask the agent
to explain any remaining limits in its delivery summary.

When the task calls for an acceptance record, ask the agent to review the current
conclusions and confirm that the required stages' published files are covered by
their latest output records. It then records the authorized acceptance through
`signoff`. If you have reserved that decision, the agent presents the evidence
and waits for your confirmation. The acceptance record is tied to that evidence;
new stage conclusions need a new acceptance when that is in scope. Ordinary
completion does not automatically record acceptance.

### Save the project

Keep the requirements, design and verification sources, constraints and evidence
needed to review the delivery. The published RTL, UVM sources, constraints,
netlist and reports can be used outside VeriPower with their required files,
libraries and environment settings.

To preserve a project you can resume, wait for active work to end and save an
independent copy of the entire module directory, including `events.jsonl`, the
published results and `runs/`. Retain the tool and library configuration too.
Published and run files can share content through hard links, so the archive
must be independent of the working copy.

## 5. Revise or resume a project

### Change the design or verification

Describe the intended change and what must remain true. For example:

> Diagnose and resolve this timing issue in {module_dir}, then run the affected checks. Preserve the required functionality and interfaces.

If you made edits yourself, identify the files and keep the changes in version
control. Ask the flow to reassess them and state which edits must be preserved.
The agent analyzes the actual impact of the change to determine which evidence
can be reused and which checks must be repeated. Depending on the implementation,
analysis conditions and measurement scope, it may repeat tool runs or reassess
existing measurements to produce a new stage conclusion.

### Change the requirements

First have the agent finish or stop active work and collect its results. Update
the original requirements in `intent/brainstorm.md` and any affected references,
rather than changing only the derived design description.

`intent/` is kept read-only by the flow. Ask the agent to restore write access
for the files and directories being revised. You can use `brainstorm` again in
a separate session to resolve the change, with the existing document as input.
Review the revised requirements, then resume `design-flow`. Changes to the
original requirements or reference contents cause reassessment across the flow.

### Continue after an interruption

Keep the module workspace and open a new session with VeriPower enabled:

> Continue the design flow for {module_dir}. Check any outstanding executors before collecting results, then resume the unfinished work.

The agent checks the project history and current files, establishes whether
previously started work is still running, and collects finished runs before
continuing. Missing or unusable results are handled as `blocked`; they are not
assumed to have passed. Previously passing results remain reusable when their
recorded inputs and outputs still match.

For the method and coordination mechanisms behind these operations, see
[Architecture](ARCHITECTURE.md).
