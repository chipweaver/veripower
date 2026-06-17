<p align="center">
  <img src="assets/logo-256.png" alt="VeriPower" width="160" />
</p>

<h1 align="center">VeriPower <small>— Verilog. Empowered. Orchestrated.</small></h1>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square"></a>
  <img alt="Status: alpha" src="https://img.shields.io/badge/status-alpha-orange?style=flat-square">
  <img alt="Version 0.1.0" src="https://img.shields.io/badge/version-0.1.0-lightgrey?style=flat-square">
</p>

---

> **An agent flow that drives chip design and verification from spec to signoff — stage-gated, replayable, auditable.**

> 🚀 **New here?** [**GETTING-STARTED.md**](GETTING-STARTED.md) walks you through running your first design flow end to end — spec to signoff. ([中文](GETTING-STARTED.zh.md))

## Why VeriPower

Chip-design teams trying to put LLMs in their EDA flow hit three structural failures:

- **Context loss across multi-hour flows.** A one-shot prompt cannot orchestrate a real specification → frontend-signoff pipeline; somewhere mid-flow, the model forgets a constraint or a prior failure and corrupts downstream work.
- **Manual stage gating doesn't scale.** Tracking which module is at which stage, which reworks are pending, and which results are stale across a portfolio of designs is a full-time human job.
- **AI-driven decisions leave no audit trail.** Production EDA tape-out review demands traceability for every decision; black-box agents fail this bar on day one.

VeriPower's answer: the state machine is cleanly separated from the LLM, deterministic rework-routing lives in a pure sibling script (`route.py`), and every dispatch is event-sourced — so the Orchestrator can't be wrong about a target over the closed-enum routing, and `state.py` remains the safety net that keeps any residual error from corrupting completed work.

## What a run looks like

Settle the module's requirements with the pre-pipeline `brainstorm` skill (its own session) until `asic/{module}/brainstorm.md` reads `Status: approved`, then ask the agent:

> Run the design flow for {module}

The `design-flow` Orchestrator bootstraps the module's state and walks the pipeline from there. A run produces:

- `asic/{module}/events.jsonl` — append-only, schema-validated event log (the audit trail).
- `asic/{module}/task.json` — current state snapshot, rebuildable by replaying the event log.
- per-stage `result.json` artifacts under `Design/` and `Verification/`, plus the terminal `frontend-signoff/result.json`.

Full step-by-step walkthrough: [`GETTING-STARTED.md`](GETTING-STARTED.md).

> **Coming soon:** sample trace excerpt + benchmark walkthrough once the first complete benchmark sweep lands.

## Pipeline at a glance

VeriPower covers the full ASIC frontend — spec through signoff, no point-tool gaps.

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

| Stage | Purpose | Primary tool |
|---|---|---|
| `brainstorm` | Pre-pipeline D0–D7 requirements brainstorm → approved `brainstorm.md` (the pipeline's input) | (human + LLM dialogue) |
| `specification` | Design spec + SDC/SGDC constraints | (human + LLM dialogue) |
| `simulation-plan` | Verification plan with testpoints + power scenarios | (LLM) |
| `rtl-design` | Verilog/SystemVerilog RTL + filelist | (LLM) |
| `lint-cdc` | Lint + clock-domain-crossing checks | Synopsys SpyGlass |
| `synthesis` | Logic synthesis with PPA (performance/power/area) self-judgment | Synopsys Design Compiler |
| `timing-analysis` | Static timing — setup/hold/slack | Synopsys PrimeTime |
| `simulation` | UVM TB materialization + regression + coverage closure | Synopsys VCS + UVM |
| `power-analysis` | GLS + SAIF + PT-PX averaged power, with PPA self-judgment | Synopsys VCS + PrimeTime PX |
| `frontend-signoff` | Aggregate checklist + traceability across all stages | (LLM) |

Full DAG semantics including rework edges live in [`ARCHITECTURE.md §3`](ARCHITECTURE.md#3-pipeline-dag).

---

## Three design decisions

### 1. Determinism boundary: judgment in the agent, state in Python

> A deterministic Python CLI (`framework/scripts/state.py`, 8 commands) owns all state; the `orchestrate.py next` reducer owns all control-loop decisions; the Orchestrator agent is a thin executor. Between every two CLI calls sits exactly one reducer call — if not, the boundary is wrong.

**For chip-design teams.** State is replayable from disk and unit-testable in Python. The bookkeeping cannot drift even when the agent does — the same property regulated EDA flows demand from their existing toolchains.

**For agent-system builders.** This is a clean pattern for splitting LLM judgment from deterministic state in a long-horizon agent. Every decision the LLM makes is bracketed by a CLI call; every CLI call has a unit test. Transferable to any multi-stage agent system.

Full mechanics: [`ARCHITECTURE.md §5`](ARCHITECTURE.md#5-orchestrator-decision-loop).

### 2. Two-dimensional stage state makes parallel rework first-class

> Each stage carries `status × freshness`; the non-obvious combination `in_progress/stale` legalizes "rework arrived mid-run" without process-killing or full-pipeline restart.

**For chip-design teams.** Real chip flows have rework storms — lint fail forces an RTL fix, which cascades stale through synthesis, timing, simulation, and power. The 2-D model handles the storm without killing what's already running — stages that were already in flight at the moment of rework finish naturally, only stale stages restart. Concurrency cap (distinct in-flight stages ≤ 2) emerges from DAG topology, not from a policy knob.

**For agent-system builders.** `in_progress/stale` is a novel state-machine value worth stealing. It says: "the work this agent is currently doing has been invalidated by an upstream change, but rather than killing it, let it finish and discard the result so we don't lose process-level invariants." A transferable idea for any rework-heavy long-horizon agent.

Full mechanics: [`ARCHITECTURE.md §4`](ARCHITECTURE.md#4-state-model).

### 3. Event-sourced audit log: events.jsonl is truth, task.json is a projection

> Eight typed event schemas with a strict "event-first, state-after" write order; `task.json` is always rebuildable by replaying `events.jsonl`. The Orchestrator can only write 3 of the 8 event types via `log` — the other 5 are side-effects of state transitions, rejected if injected externally, so the audit log cannot be forged.

**For chip-design teams.** Every AI-driven decision in the design flow leaves a tamper-evident record — the table-stakes property that converts an "AI demo" into a production-defensible EDA tool. Crash recovery is a free side effect: if a write crashes between event and state, the event already exists and replay reconstructs the state.

**For agent-system builders.** Classic event sourcing applied to agent orchestration — mature in distributed systems, rare in agent design. The forgery-resistance pattern (only some event types are agent-writable) is a useful primitive for any agent system that needs to be auditable.

Full mechanics: [`ARCHITECTURE.md §4`](ARCHITECTURE.md#4-state-model) (event types) and [Appendix A](ARCHITECTURE.md#appendix-a-replay-algorithm) (replay algorithm).

## Swappable execution layer

VeriPower separates orchestration from execution:

- **Orchestration layer (tool-agnostic):** `framework/scripts/state.py`, `framework/references/schemas/`, the DAG itself.
- **Execution layer (vendor-bound):** each `skills/<stage>/` is a Claude Code skill that wraps one or more vendor tools.
- **Extension seam:** swap a single skill (e.g., a Verilator-backed `simulation` or a Yosys-backed `synthesis`) without touching the orchestration. `framework/scripts/topology.py`'s `SKILL_OF` mapping is the pivot.

The reference implementation ships Synopsys-backed skills because that's the toolchain our use cases target. No promises about FOSS-tool skills today — but the seam is real, not aspirational.

## Install & first run (Claude Code plugin)

```bash
# launch Claude Code with the plugin
claude --plugin-dir /path/to/veripower
```

Then settle requirements with the `brainstorm` skill and ask the agent in chat to *"Run the design flow for {module}"*. The full step-by-step walkthrough is in **[`GETTING-STARTED.md`](GETTING-STARTED.md)**.

**What you'll need.** Commercial Synopsys EDA tools — SpyGlass (lint+CDC), Design Compiler (synthesis), PrimeTime (timing), VCS+UVM (simulation), PrimeTime PX (power). Swappable per skill — see [Swappable execution layer](#swappable-execution-layer). Python 3 + `jsonschema` + `referencing` are the only Python dependencies (`requirements.txt`).

## Repository layout

```
veripower/
├── ARCHITECTURE.md          # full design spec
├── GETTING-STARTED.md       # run your first design flow, end to end
├── CLAUDE.md                # project instructions auto-loaded by Claude Code
├── README.md                # this file
├── LICENSE                  # MIT
├── .claude-plugin/          # plugin manifest
├── skills/                  # one skill per pipeline stage + orchestrator + triage
├── framework/               # state.py + JSON schemas + prompt template
├── docs/                    # auxiliary design docs (schema, skill authoring)
└── tests/                   # unit / contracts / scenarios (three tiers)
```

## Tests

Three tiers, each answering a different question: **`tests/unit/`** (pure-Python code behavior), **`tests/contracts/`** (deterministic artifact-sync / invariant lints, no code executed), and **`tests/scenarios/`** (skill-level agent-discipline regression — Claude as the system under test, no EDA tools). How to run each, the fast loop, and the CI gate are in [CONTRIBUTING.md § Testing](CONTRIBUTING.md#testing).
## Status, license, contributing

- **Status:** alpha (v0.1.0). Stable interfaces: the `state.py` CLI surface and the cross-stage envelope schema. Unstable: skill internals.
- **License:** MIT. See [`LICENSE`](LICENSE).
- **Contributing:** the contribution model is documented in [`CONTRIBUTING.md`](CONTRIBUTING.md). For now, please file issues at <https://github.com/chipweaver/veripower/issues>.
