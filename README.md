<p align="center">
  <img src="assets/logo-256.png" alt="VeriPower" width="160" />
</p>

<h1 align="center">VeriPower <small>— Verilog. Empowered. Orchestrated.</small></h1>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square"></a>
  <img alt="Status: alpha" src="https://img.shields.io/badge/status-alpha-orange?style=flat-square">
  <img alt="Version 0.1.4" src="https://img.shields.io/badge/version-0.1.4-lightgrey?style=flat-square">
</p>

---

> **An agent flow that drives chip design and verification from spec to signoff — stage-gated, replayable, auditable.**

> 🚀 **New here?** [**GETTING-STARTED.md**](GETTING-STARTED.md) walks you through running your first design flow end to end — spec to signoff. ([中文](GETTING-STARTED.zh.md))

## Why VeriPower

Chip-design teams trying to put LLMs in their EDA flow hit three structural failures:

- **Context loss across multi-hour flows.** A one-shot prompt cannot orchestrate a real specification → signoff pipeline; somewhere mid-flow, the model forgets a constraint or a prior failure and corrupts downstream work.
- **Manual stage gating doesn't scale.** Tracking which module is at which stage, which reworks are pending, and which results are stale across a portfolio of designs is a full-time human job.
- **AI-driven decisions leave no audit trail.** Production EDA tape-out review demands traceability for every decision; black-box agents fail this bar on day one.

VeriPower's answer: the deterministic scheduling core is cleanly separated from the LLM, deterministic rework-routing lives in a pure sibling script (`route.py`), and every dispatch is event-sourced — so the Orchestrator can't be wrong about a target over the closed-enum routing, and `kernel.py`'s append-only event log remains the safety net that keeps any residual error from corrupting completed work.

## What a run looks like

Settle the module's requirements with the pre-pipeline `brainstorm` skill (its own session) until `{module_dir}/brainstorm.md` says what you mean, then ask the agent:

> Run the design flow for {module_dir}

The `design-flow` Orchestrator bootstraps the module's state and walks the pipeline from there. A run produces:

- `{module_dir}/events.jsonl` — append-only, schema-validated event log; the **sole** durable state file (the audit trail).
- per-stage status is **not** persisted — it is computed on demand from the event log + disk fingerprints (`kernel.py status`), so it can never drift from what's on disk.
- per-stage `result.json` artifacts under `Design/` and `Verification/`.

Full step-by-step walkthrough: [`GETTING-STARTED.md`](GETTING-STARTED.md).

> **Coming soon:** sample trace excerpt + benchmark walkthrough once the first complete benchmark sweep lands.

## Pipeline at a glance

VeriPower covers the full ASIC frontend — spec through signoff, no point-tool gaps.

```
[brainstorm] (pre-pipeline, own session) → brainstorm.md ↓

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
```

| Stage | Purpose | Primary tool |
|---|---|---|
| `brainstorm` | Pre-pipeline D0–D7 requirements brainstorm → `brainstorm.md` (the pipeline's input) | (human + LLM dialogue) |
| `specification` | Design spec + SDC/SGDC constraints | (human + LLM dialogue) |
| `simulation-plan` | Verification plan with testpoints + power scenarios | (LLM) |
| `rtl-design` | Verilog/SystemVerilog RTL + filelist | (LLM) |
| `lint-cdc` | Lint + clock-domain-crossing checks | Synopsys SpyGlass |
| `synthesis` | Logic synthesis with PPA (performance/power/area) self-judgment | Synopsys Design Compiler |
| `timing-analysis` | Static timing — setup/hold/slack | Synopsys PrimeTime |
| `simulation` | UVM TB materialization + regression + coverage closure | Synopsys VCS + UVM |
| `power-analysis` | GLS + SAIF + PT-PX averaged power, with PPA self-judgment | Synopsys VCS + PrimeTime PX |

Signoff is not a stage. Once every proof is valid and a human has pinned each LLM-proposed
judge, `kernel.py signoff` closes the module — the third ask-gated judgment verb beside
`pin`/`reopen`. See [`ARCHITECTURE.md §5.5`](ARCHITECTURE.md#55-signoff-closure).

Full dependency-graph semantics live in [`ARCHITECTURE.md §3`](ARCHITECTURE.md#3-rule-registry-and-the-derived-dependency-graph).

---

## Three design decisions

### 1. Determinism boundary: judgment in the agent, state in Python

> A deterministic Python CLI (`framework/scripts/kernel.py`, 10 verbs) is the sole writer of all state and `kernel.py decide` (implemented in `schedule.py`) owns all control-loop decisions; the Orchestrator agent is a thin executor. Every state-mutating call is bracketed by a `decide` — two consecutive mutating calls with no `decide` between them is a bug.

**For chip-design teams.** State is replayable from disk and unit-testable in Python. The bookkeeping cannot drift even when the agent does — the same property regulated EDA flows demand from their existing toolchains.

**For agent-system builders.** This is a clean pattern for splitting LLM judgment from deterministic state in a long-horizon agent. Every decision the LLM makes is bracketed by a CLI call; every CLI call has a unit test. Transferable to any multi-stage agent system.

Full mechanics: [`ARCHITECTURE.md §5`](ARCHITECTURE.md#5-scheduler-decision-loop).

### 2. Validity is a query, not a stored flag

> No stage carries a stored `stale` bit. A stage's output is trusted only while a *proof* it recorded still holds — its recorded input and output fingerprints still match disk and its oracle is un-reopened. Edit an upstream file and every proof whose fingerprints no longer match silently becomes invalid on the next query; nothing has to remember to mark it stale.

**For chip-design teams.** Real chip flows have rework storms — a lint fail forces an RTL fix, which invalidates synthesis, timing, simulation, and power downstream. Because staleness is recomputed from content rather than tracked as a flag, editing the RTL auto-expires exactly the downstream proofs that consumed it — and a stage already in flight at that moment finishes and has its result re-checked rather than being killed. The concurrency cap (at most two distinct rules in flight) emerges from the derived dependency graph, not from a policy knob.

**For agent-system builders.** "Recompute trust from content, never store it" is the idea worth stealing. A stored `stale` flag is a fact that can drift from reality the instant someone forgets to update it; a content-fingerprint query cannot. Any rework-heavy long-horizon agent that must answer "is this earlier result still good?" can borrow the pattern.

Full mechanics: [`ARCHITECTURE.md §4`](ARCHITECTURE.md#4-state-model-the-event-log).

### 3. Event-sourced audit log: events.jsonl is the only durable state

> Seven typed, schema-validated event types in one append-only log; there is no `task.json` and no status snapshot — every stage's status is *derived* from the log plus disk fingerprints on demand. `kernel.py` is the sole writer of all seven event types and validates each against its schema at write time, so the audit log cannot be forged through an agent prompt.

**For chip-design teams.** Every AI-driven decision in the design flow leaves a tamper-evident record — the table-stakes property that converts an "AI demo" into a production-defensible EDA tool. Crash recovery is a free side effect: a run whose executor died left a `dispatch` with no matching `outcome`, so it still reads as in-flight and the next `decide` reaps it — no separate recovery phase.

**For agent-system builders.** Classic event sourcing applied to agent orchestration — mature in distributed systems, rare in agent design. The forgery-resistance pattern (a single validated writer, with no agent-writable event channel) is a useful primitive for any agent system that needs to be auditable.

Full mechanics: [`ARCHITECTURE.md §4`](ARCHITECTURE.md#4-state-model-the-event-log) (the seven event types and the projection contract).

## Swappable execution layer

VeriPower separates orchestration from execution:

- **Orchestration layer (tool-agnostic):** `framework/scripts/kernel.py`, `framework/references/schemas/`, and the rule registry (`rules.py`).
- **Execution layer (vendor-bound):** each `skills/<stage>/` is a Claude Code skill that wraps one or more vendor tools.
- **Extension seam:** swap a single skill (e.g., a Verilator-backed `simulation` or a Yosys-backed `synthesis`) without touching the orchestration. Each rule's `skill` field in `framework/scripts/rules.py` (`RULES`) is the pivot.

The reference implementation ships Synopsys-backed skills because that's the toolchain our use cases target. No promises about FOSS-tool skills today — but the seam is real, not aspirational.

## Install & first run (Claude Code plugin)

```bash
claude plugin marketplace add chipweaver/veripower
claude plugin install veripower@chipweaver
```

Or, to run a working copy without installing it: `claude --plugin-dir /path/to/veripower`.

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
├── .claude-plugin/          # plugin + marketplace manifests
├── skills/                  # one skill per pipeline stage + orchestrator + triage
├── framework/               # kernel.py + rule registry + JSON schemas + prompt template
├── hooks/                   # shipped ask-gate over the pin/reopen/signoff judgment verbs
├── docs/                    # auxiliary design docs (schema, skill authoring)
└── tests/                   # unit / contracts / scenarios (three tiers)
```

## Tests

Three tiers, each answering a different question: **`tests/unit/`** (pure-Python code behavior), **`tests/contracts/`** (deterministic artifact-sync / invariant lints, no code executed), and **`tests/scenarios/`** (skill-level agent-discipline regression — Claude as the system under test, no EDA tools). How to run each, the fast loop, and the CI gate are in [CONTRIBUTING.md § Testing](CONTRIBUTING.md#testing).
## Status, license, contributing

- **Status:** alpha (v0.1.4). Stable interfaces: the `kernel.py` CLI surface and the cross-stage envelope schema. Unstable: skill internals.
- **License:** MIT. See [`LICENSE`](LICENSE).
- **Contributing:** the contribution model is documented in [`CONTRIBUTING.md`](CONTRIBUTING.md). For now, please file issues at <https://github.com/chipweaver/veripower/issues>.
