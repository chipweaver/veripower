<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-text-dark.png">
    <img alt="VeriPower" src="assets/logo-text-light.png" width="320">
  </picture>
</p>

<h3 align="center">Chip front-end design and verification with coding agents</h3>

<!-- <p align="center"><a href="">Paper</a></p> -->

---

VeriPower is an open-source plugin for chip front-end design and verification. Working from your specification, a coding agent develops RTL and a UVM testbench, runs EDA tools, and revises the design based on their results. VeriPower manages the work across stages, keeping track of what has passed and what needs to run again.

Works with [Claude Code](.claude-plugin/README.md), [opencode](.opencode/README.md), [DeepSeek Harness](.dsh/README.md), and [Codex](codex/README.md).

## How it works

Each stage has a skill containing instructions and supporting scripts. The agent follows the skill to carry out the work, while a workflow engine records the result and selects what should run next. When a check fails, the agent investigates the cause and the engine schedules the repair.

<p align="center">
  <img src="assets/plugin-architecture.png" alt="VeriPower plugin, coding agent, EDA tools, and engineer interactions" width="680" />
</p>

Each run records the versions of its input and output files. The engine compares these with the current files to determine which results still apply and which checks need to be repeated. An RTL edit requires simulation, lint/CDC, and synthesis to run again, while a testbench edit leaves lint/CDC results intact. The files and execution history are stored on disk, allowing work to resume in a new session.

The verification plan and reference model are based on the specification. Stage scripts verify that every planned test ran and passed, and check coverage, timing, and power against the specified targets. Independent model reviews examine whether the test stimulus and checking logic can detect incorrect behavior. Together, these checks and reviews determine whether a stage passes.

Before the flow completes, the engine checks that all required stages have passed and their results still apply. The generated RTL, testbench, constraints, and reports are available in the project directory.

More in the [architecture guide](ARCHITECTURE.md) ([中文](ARCHITECTURE.zh.md)).

## Design flow

The flow covers eight stages, from specification to power analysis. Simulation triage is a separate task that investigates simulation failures when the cause is unclear.

<p align="center">
  <img src="assets/pipeline-dag.png" alt="Pipeline dependency graph" width="660" />
</p>

The included skills use Synopsys SpyGlass for lint and CDC, Design Compiler for synthesis, PrimeTime for timing and power analysis, and VCS with UVM for simulation.

## Results

Three front-end design tasks, bare Claude Code vs. Claude Code + VeriPower. Same LLM, same spec, same EDA tools.

| Benchmark | Scale | Baseline | + VeriPower |
|---|---|---|---|
| gateGPT — fixed-point GPT inference | 346K gates | 3 of 4 coverage metrics below 90% | **pass** |
| FSA — FlashAttention accelerator | 32K gates | 2 unresolved CDC violations | **pass** |
| Coral-NPU — RISC-V ML accelerator | 3.4M gates | 6/19 tests | **19/19** |

Across these tasks, VeriPower closes verification gaps in coverage, CDC and test execution.

## Quickstart

<details>
<summary><strong>Claude Code</strong></summary>

```bash
claude plugin marketplace add chipweaver/veripower
claude plugin install veripower@chipweaver
```

Or point at a working copy: `claude --plugin-dir /path/to/veripower`.

See [Claude Code setup and runtime behavior](.claude-plugin/README.md).

</details>

<details>
<summary><strong>opencode</strong></summary>

Add the plugin to `~/.config/opencode/opencode.json`, or to a project-level
`opencode.json`:

```json
{ "plugin": ["veripower@git+https://github.com/chipweaver/veripower.git"] }
```

Stage dispatch runs subagents in the background, which opencode gates behind an environment
variable, so start it with:

```bash
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true \
OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=131072 opencode
```

opencode 1.18.30 has a default 32,000-token completion ceiling. For models that support
longer output, set the second flag to the model's declared output limit; `131072` is
an example.

See [opencode setup and runtime behavior](.opencode/README.md).

</details>

<details>
<summary><strong>DeepSeek Harness</strong></summary>

Install into the profile you run:

```bash
dsh plugin --profile web add "veripower@git+https://github.com/chipweaver/veripower.git"
```

Run the `web` profile (`dsh web`), not the one-shot `headless` profile.

See [DeepSeek Harness setup and runtime behavior](.dsh/README.md).

</details>

<details>
<summary><strong>Codex</strong></summary>

Native plugin and subagents (tested with CLI 0.154.0 on Linux):

```bash
codex plugin marketplace add chipweaver/veripower
codex plugin add veripower@chipweaver --json
```

Launch with `codex --enable hooks --enable multi_agent`, review the two VeriPower hooks in
`/hooks`, and start a new session. The plugin uses native subagents and preserves the host's
permission configuration. See [Codex setup and runtime behavior](codex/README.md).

</details>

Ask it to list its skills — the twelve VeriPower ones confirm the install.

Run the `brainstorm` skill to settle requirements first, then tell the agent:

> Run the design flow for {module_dir}

Full walkthrough in the [user manual](docs/USER-MANUAL.md) ([中文](docs/USER-MANUAL.zh.md)).

**Requirements.** Python 3.10+, `jsonschema` >= 4.18, `referencing`, `PyYAML`. Synopsys EDA tools, swappable per skill.

## Citation

Paper forthcoming.

<!--
```bibtex
@article{veripower2026,
  title   = {VeriPower: Agent-Driven Chip Design and Verification},
  author  = {TODO},
  journal = {arXiv preprint arXiv:TODO},
  year    = {2026}
}
```
-->

**Version:** v0.2.5. [MIT License](LICENSE). [Contributing](CONTRIBUTING.md). [Issues](https://github.com/chipweaver/veripower/issues).
