# Getting Started with VeriPower

> Drive one module from idea to frontend-signoff. This guide walks the whole
> flow once, end to end, using a placeholder module name `{module}` —
> substitute your own. It is the *how*; for *why* VeriPower is built this way,
> see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## How it runs, in one minute

VeriPower turns an approved idea into a signed-off frontend design through a
10-stage pipeline. Two things shape how you'll experience it:

- **Brainstorm comes first, in its own session.** Before the pipeline, you run
  the `brainstorm` skill to settle requirements and architecture; it produces a
  frozen `asic/{module}/brainstorm.md`. The pipeline starts only once that file
  reads `Status: approved`.
- **One sentence starts the pipeline.** You tell the agent *"Run the design
  flow for {module}"* and the `design-flow` Orchestrator takes over — it
  bootstraps the module's state, then walks the stage graph, dispatching each
  stage and recording every step.

It is **not** fully hands-off. You have exactly three touchpoints:

1. The **brainstorm** dialogue (before the pipeline).
2. **Approving the verification plan** when `simulation-plan` presents it.
3. **Answering escalations** — the rare moments the flow needs a human decision.

Everything else runs autonomously and reports as it goes. Every decision is
appended to an audit log (`events.jsonl`), and you can ask for status at any
time.

## Prerequisites

- **Claude Code with the plugin loaded:**
  ```bash
  claude --plugin-dir /path/to/veripower
  ```
- **Python 3** plus the two dependencies in [`requirements.txt`](requirements.txt)
  (`jsonschema`, `referencing`).
- **EDA tools — for the tool-gated stages only.** Five stages invoke commercial
  Synopsys tools (`lint-cdc` → SpyGlass, `synthesis` → Design Compiler,
  `timing-analysis` → PrimeTime, `simulation` → VCS + UVM, `power-analysis` →
  PrimeTime PX) and need the environment described in
  [`docs/eda-env.md`](docs/eda-env.md) — tools on `PATH`, a license server, and
  the `LIB_DB` / `LIB_V` / `UVM_HOME` variables. The other five stages
  (`brainstorm`, `specification`, `simulation-plan`, `rtl-design`,
  `frontend-signoff`) run on Claude Code + Python alone.

## The pipeline

```
[brainstorm] (pre-pipeline, own session) → approved brainstorm.md ↓

[specification] → [simulation-plan] → [rtl-design]
                                            │
                          ┌─────────────────┴──────────────────┐
                          ↓                                    ↓
                     [lint-cdc]                          [simulation]
                          │                                    │
                          ↓                                    │
                     [synthesis]                               │
                          │                                    │
                          ↓                                    │
                  [timing-analysis]                            │
                          │                                    │
                          └─────────────────┬──────────────────┘
                                            ↓
                                    [power-analysis]
                                            │
                                            ↓
                                    [frontend-signoff]
```

## Step 1 — Brainstorm the module

In its own session, ask the agent to brainstorm your module — this runs the
`brainstorm` skill:

> Brainstorm a new module called {module}

It runs a structured D0–D7 dialogue (requirements, interfaces, architecture —
one question at a time) and writes `asic/{module}/brainstorm.md`. Review it and
set its frontmatter to `Status: approved`. That frozen file is the pipeline's
sole upstream input — the pipeline never re-opens the brainstorm conversation.

> **[Captured run — coming soon]** A real brainstorm excerpt will be dropped in
> here once the first benchmark sweep lands.

## Step 2 — Kick off the flow

In a session with the plugin loaded, tell the agent:

> Run the design flow for {module}

The `design-flow` Orchestrator verifies the approved `brainstorm.md`, sets up
the module's state, and begins walking the pipeline. From here you mostly
watch — stepping in only at the touchpoints below.

> **[Captured run — coming soon]** Kickoff transcript here.

## Step 3 — What runs, and where you come in

The Orchestrator dispatches stages in dependency order. The two earliest stages
differ in how much they involve you:

- **`specification` (autonomous).** Derives the frozen design source of truth
  from your brainstorm: `design.md`, the per-child sub-designs, `manifest.json`,
  `coverage.json`, and the constraint pair (`<TOP>.sdc` / `<TOP>.sgdc`). No
  dialogue — it reads the approved brainstorm and produces the spec.
- **`simulation-plan` (your review).** Drafts the verification plan (testpoints
  + power scenarios) and **presents `verification-plan.md` for your approval**.
  The stage passes only after you approve.

After that, the remaining stages run autonomously and report their results:
`rtl-design` runs, then the graph forks into the implementation-signoff branch
(`lint-cdc` → `synthesis` → `timing-analysis`) and the `simulation` branch;
the branches rejoin at `power-analysis`, then `frontend-signoff`.

**Checking progress at any time** — just ask the agent:

> Where is {module}?

That routes back into `design-flow`, which reports each stage's status from
`task.json`. Each stage also leaves a `result.json` on disk — under `Design/`
for design stages, `Verification/` for verification stages.

> **[Captured run — coming soon]** A real status snapshot here.

## Step 4 — When a stage fails (rework)

Stage failures are **routed automatically** — a deterministic reducer picks the
rework target and the Orchestrator re-dispatches the right stage. You don't
route anything by hand, and work already in flight isn't thrown away. (The full
state model and rework edges live in [`ARCHITECTURE.md §3`](ARCHITECTURE.md#3-pipeline-dag)
and [`§4`](ARCHITECTURE.md#4-state-model).)

One failure escalates to **you**: when the requirements themselves need to
change, `specification` escalates with a `fail_reason` of *"requirements need
revision: …"*. To recover:

1. Re-run the `brainstorm` skill and re-approve the updated `brainstorm.md`.
2. Invalidate the spec so the pipeline re-derives from the new brainstorm:
   ```bash
   python3 framework/scripts/state.py invalidate-stage \
       --module {module} --stage specification --reason "<why>"
   ```
3. Ask the agent to run the design flow again.

> **[Captured run — coming soon]** A real rework example here.

## Step 5 — Read the signoff

`frontend-signoff` aggregates a checklist and cross-stage traceability into
`asic/{module}/frontend-signoff/result.json` — the terminal verdict for the run.

Behind it sits the audit trail every run produces:

- `asic/{module}/events.jsonl` — append-only, schema-validated event log (the
  source of truth).
- `asic/{module}/task.json` — the current state snapshot, rebuildable by
  replaying the event log.

> **[Captured run — coming soon]** A real signoff result here.

## Where to go next

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the pipeline DAG, rework edges, and
  design rationale.
- [`docs/eda-env.md`](docs/eda-env.md) — the EDA tool / license / environment
  setup for the tool-gated stages.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — extending or swapping a stage skill.
