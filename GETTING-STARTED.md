# Getting Started with VeriPower

> Drive one module from idea to a closed signoff. This guide walks the whole
> flow once, end to end, using a placeholder module name `{module}` —
> substitute your own. It is the *how*; for *why* VeriPower is built this way,
> see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## How it runs, in one minute

VeriPower turns an approved idea into a signed-off frontend design through a
9-stage pipeline. Two things shape how you'll experience it:

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

- **Claude Code with the plugin installed:**
  ```bash
  claude plugin marketplace add chipweaver/veripower
  claude plugin install veripower@chipweaver
  ```
  To run a working copy instead: `claude --plugin-dir /path/to/veripower`.
- **Python 3** plus the two dependencies in [`requirements.txt`](requirements.txt)
  (`jsonschema`, `referencing`).
- **EDA tools — for the tool-gated stages only.** Five stages invoke commercial
  Synopsys tools (`lint-cdc` → SpyGlass, `synthesis` → Design Compiler,
  `timing-analysis` → PrimeTime, `simulation` → VCS + UVM, `power-analysis` →
  PrimeTime PX) and need the environment described in
  [`docs/eda-env.md`](docs/eda-env.md) — tools on `PATH`, a license server, and
  the `LIB_DB` / `LIB_V` / `UVM_HOME` variables. The other four stages
  (`brainstorm`, `specification`, `simulation-plan`, `rtl-design`) run on
  Claude Code + Python alone.

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
                                 kernel.py signoff  (you, Step 5)
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
  and the constraint pair (`<TOP>.sdc` / `<TOP>.sgdc`). No dialogue — it reads
  the approved brainstorm and produces the spec.
- **`simulation-plan` (your review).** Drafts the verification plan (testpoints
  + power scenarios) and **presents `verification-plan.md` for your approval**.
  The stage passes only after you approve.

After that, the remaining stages run autonomously and report their results:
`rtl-design` runs, then the graph forks into the implementation-signoff branch
(`lint-cdc` → `synthesis` → `timing-analysis`) and the `simulation` branch;
the branches rejoin at `power-analysis`, which ends the pipeline. Closing signoff
is a separate act you request (Step 5).

**Checking progress at any time** — just ask the agent:

> Where is {module}?

That routes back into `design-flow`, which reports each stage's status —
computed on demand from the event log and disk fingerprints (`kernel.py
status`), never read from a stored snapshot. Each stage also leaves a
`result.json` on disk — under `Design/` for design stages, `Verification/` for
verification stages.

> **[Captured run — coming soon]** A real status snapshot here.

## Step 4 — When a stage fails (rework)

Stage failures are **routed automatically** — a deterministic decider picks the
rework target and the Orchestrator re-dispatches the right stage. You don't
route anything by hand, and work already in flight isn't thrown away. (The full
dependency graph and state model live in [`ARCHITECTURE.md §3`](ARCHITECTURE.md#3-rule-registry-and-the-derived-dependency-graph)
and [`§4`](ARCHITECTURE.md#4-state-model-the-event-log).)

One failure escalates to **you**: when the requirements themselves need to
change, `specification` escalates with a `fail_reason` of *"requirements need
revision: …"*. To recover:

1. Re-run the `brainstorm` skill and re-approve the updated `brainstorm.md`.
2. That's the whole invalidation. `brainstorm.md` is `specification`'s recorded
   input, so editing it makes the spec's proof fingerprints no longer match
   disk — the stage auto-expires as stale on the next query, and every
   downstream proof that consumed the spec expires with it. There is no
   invalidate command to run.
3. Ask the agent to run the design flow again — `decide` re-derives from the
   new brainstorm and rebuilds the expired stages.

> **[Captured run — coming soon]** A real rework example here.

## Step 5 — Close the signoff

Delivery gets every stage to a valid proof. Signoff is a separate, deliberate act:
ask for it, and the flow loops `decide --objective signoff`, which requires the same
proofs to clear a stricter gate — every proof valid, no unverified file smuggled in,
and **every LLM-authored judge pinned by you**. Anything short of that comes back as
`ESCALATE` naming what blocks it (usually "pin it").

When the gate is clear, nothing is signed off yet — you are. With your approval the
flow runs:

```bash
kernel.py signoff --module {module} --provenance <you> --reason "<why>"
```

That records who closed the module and why. `kernel.py status` then reports
`signed_off: true` — but only for as long as every proof beneath it stays valid. Edit
a design file or `reopen` a pin and it drops back on its own; a signoff is only as
good as the proofs beneath it.

Behind it sits the audit trail every run produces:

- `asic/{module}/events.jsonl` — append-only, schema-validated event log; the
  **sole** durable state file (the source of truth).
- per-stage status — **not** stored anywhere; `kernel.py status` computes it on
  demand from the event log and disk fingerprints, so it can never drift from
  what's on disk.

> **[Captured run — coming soon]** A real signoff close here.

## Where to go next

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the rule registry, derived dependency
  graph, and design rationale.
- [`docs/eda-env.md`](docs/eda-env.md) — the EDA tool / license / environment
  setup for the tool-gated stages.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — extending or swapping a stage skill.
