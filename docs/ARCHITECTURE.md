# VeriPower Architecture

[中文版](ARCHITECTURE.zh.md)

## Overall design

VeriPower is a chip front-end development method for coding agents, implemented
as a plugin for general-purpose agent harnesses such as Claude Code, OpenCode,
DeepSeek Harness and Codex. It takes a spiral approach to
iterative development: design and checking evolve together through continuing
feedback and coordinated revisions under shared functional requirements and
power, performance and area (PPA) targets. Completing a development task requires
the necessary artifacts to be present, meet requirements and remain mutually
consistent, as well as the prescribed activities to have been performed.

**Domain-specific skills** provide professional guidance for design reasoning,
requirements-driven verification and revision analysis. Stage scripts support
tool execution and checking. **The workflow engine** coordinates execution using
artifact dependencies and run records. An orchestrating agent uses the harness
to arrange task execution and collect results.

<!-- Reused unchanged from the VeriPower paper. -->
<p align="center">
  <a href="../assets/veripower-methodology-and-mechanisms.png">
    <img src="../assets/veripower-methodology-and-mechanisms.png" alt="Design and checking evolve under shared requirements; an orchestrating agent connects stage execution with workflow coordination" width="960" />
  </a>
  <br>
  <sub>Development method and execution mechanisms · <a href="../assets/veripower-methodology-and-mechanisms.png">View full size</a></sub>
</p>

## Development tasks and domain guidance

Each development task specifies its inputs, objective, domain guidance and
deliverables. A technical task with its own delivery and assessment
responsibilities is a **stage**. Its executor develops and checks the artifacts
within that scope and submits a verdict with supporting evidence.

Domain guidance covers three closely related activities:

- **Design reasoning.** Specification and RTL tasks combine top-down requirements
  refinement with bottom-up feasibility analysis. The specification establishes
  shared boundaries and constraints; the RTL executor uses the design rationale
  to choose the internal decomposition.
- **Requirements-driven verification.** Verification planning starts from the
  specification once it has passed its own checks. Expected behavior is derived
  from requirements and independent references. Independent reviews assess whether stimuli,
  observations and checking logic can detect violations and trigger test failure.
  Simulation, static checks and PPA analysis provide further feedback.
- **Revision analysis.** Executors combine diagnosis with change-impact analysis
  to identify the task responsible for a repair and assess its effects on other
  requirements and artifact consistency.

Shared requirements connect these tasks. The specification organizes original
requirements into a ledger with stable identifiers. Design decisions, testpoints,
measurements and verdicts refer to requirements through these identifiers.
The ledger and specification are checked against the original materials when
created or revised, keeping design and checking grounded in the task requirements.

Stage scripts check artifact structure, execution results and supported numerical
targets. Executors assess the analysis scope and measurement meaning against
requirements and report their technical judgments. The stage CLI records these
results in the common result format. A stage's pass verdict concerns its own
delivery and checking scope; subsequent feedback can confirm or revise the
design choices on which it depends.

## Coordinating development across iterations

### Tasks, artifacts and stage conclusions

Stage declarations define inputs and artifact ownership. The production and use
of artifacts form the dependency graph used for scheduling and repair routing.
Executors revise artifacts owned by their task. When feedback
requires changes to shared design decisions or another task's artifacts, the
responsible task performs the revision, coordinated with affected work.

Task handoff and result submission connect technical work to process coordination.
The orchestrating agent asks the engine to select work from the current artifacts
and run records. The handoff provides inputs, existing artifacts and reasons for
rework. The orchestrator arranges stage execution in the main conversation or a
background subagent according to the stage declaration. After confirming executor
completion through the harness, it asks the engine to collect the result, publish
artifacts and update the run records before deciding what to do next.

Each run records its declared input versions and delivered output versions,
linking the stage conclusion to those artifacts:

<!-- Reused unchanged from the VeriPower paper. -->
<p align="center">
  <a href="../assets/veripower-task-artifact-relations.png">
    <img src="../assets/veripower-task-artifact-relations.png" alt="A task uses inputs, produces outputs and reports a verdict and evidence; the conclusion is associated with recorded input and output versions" width="800" />
  </a>
  <br>
  <sub>Tasks, artifacts and conclusions · <a href="../assets/veripower-task-artifact-relations.png">View full size</a></sub>
</p>

The latest collected result supplies a stage's current conclusion. A passing
result remains applicable when the inputs and outputs recorded for its run are
readable and match their fingerprints. A later failed or blocked result supersedes
an earlier pass. Version checks associate conclusions with current artifacts;
their technical meaning is determined by the checking method and its analysis scope.

### Diagnosis and coordinated revision

Consider a simulation that finds an output error on a valid input. The executor
examines the implementation, expected values and test setup to establish the cause.
If the defect is in the RTL, the RTL task uses the diagnosis to revise its
implementation. A precision
repair might add cycles or control states, so the assessment also considers the
latency budget, reset behavior and related tests.

Eligible repair tasks are the failed stage itself and the upstream tasks that
directly or indirectly supply its inputs. The engine consolidates problems
assigned to the same task into one rework run. When simulation fails and repair
responsibility is unclear, a dedicated diagnosis task investigates the failed run.
Unresolved attribution returns to the orchestrator for further investigation or
a decision under the task's authorization.

The engine identifies potentially affected tasks from artifact dependencies.
Executors analyze the actual impact to determine which evidence can be reused
and which checks must be repeated. Independent tasks may run concurrently;
checks depending on a revision wait for upstream rework, available inputs and
current passing producer results. Subsequent iterations can then build on
existing artifacts and applicable conclusions.

### Continuity and completion

Artifacts and run records persist in the module workspace and support work across
iterations and sessions.
After an interruption, the orchestrator identifies uncollected runs, checks
whether their executors are still running and resumes pending work. The engine
records collection, while the harness provides executor completion information.

The flow completes when every required stage has a passing result applicable to
the current artifacts and all dispatched runs have been collected. The
orchestrator consolidates verdicts and technical evidence against the original
requirements and reports any remaining limits.

When the task calls for an acceptance record, the orchestrator uses
`decide --closing` to check that the required stages' published files are covered
by their latest output records, excluding run history. It then records the
authorized acceptance through `signoff`, binding the decision to that evidence.

## Integration and implementation

The agent harness supplies model interaction, context, file and shell tools,
subagents and execution permissions.
Adapters map the shared skills and orchestration onto those native facilities.
EDA tools execute outside the agent and produce the reports and artifacts used
by the stages. Engineers provide requirements and delegate decisions; task
authorization is separate from the execution permissions enforced by the harness.

The implementation follows these boundaries:

| Responsibility | Entry point |
|---|---|
| Engineering methods, reviews and tool work | [Stage skills](../skills/), with their references and scripts |
| Stage result interface | [Shared result schema](../framework/references/schemas/envelope.schema.json) |
| Agent orchestration | [design-flow](../skills/design-flow/SKILL.md) |
| Task declarations and artifact dependencies | [rules.py](../framework/scripts/rules.py) |
| Result validity, scheduling and publication | [kernel.py](../framework/scripts/kernel.py) and the [framework components](../framework/README.md) |
| Agent harness integration | [Claude Code](../.claude/README.md), [OpenCode](../.opencode/README.md), [DeepSeek Harness](../.dsh/README.md), [Codex](../.codex-plugin/README.md) |

Preparation, operation and review of deliveries are covered in the
[user guide](USER-MANUAL.md). Development and validation practices are in
[Contributing](../CONTRIBUTING.md).
