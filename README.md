<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-text-dark.png">
    <img alt="VeriPower" src="assets/logo-text-light.png" width="320">
  </picture>
</p>

<h3 align="center">Chip front-end design and verification with coding agents</h3>

<p align="center">English | <a href="README.zh.md">中文</a></p>

---

VeriPower helps coding agents develop chip front-end designs from original
requirements through implementation, verification and power, performance and
area (PPA) evaluation. Its goal is a complete delivery in which the implementation
and its checking artifacts jointly meet the task requirements.

Implemented as an open-source plugin for agent harnesses such as Claude Code,
OpenCode, DeepSeek Harness and Codex, VeriPower combines professional guidance
from domain-specific skills with a workflow engine. Design and checking evolve together
through continuing feedback and coordinated revisions under shared requirements.

<p align="center">
  <a href="assets/veripower-methodology-and-mechanisms.png">
    <img src="assets/veripower-methodology-and-mechanisms.png" alt="Design and checking evolve under shared requirements; an orchestrating agent and workflow engine coordinate task execution across iterations" width="960">
  </a>
  <br>
  <sub>Development method and execution mechanisms · <a href="assets/veripower-methodology-and-mechanisms.png">View full size</a></sub>
</p>

## What it provides

- **Design reasoning and early feedback.** Functional requirements and PPA
  targets guide specification and RTL design. Top-down requirements refinement
  and bottom-up feasibility analysis inform structural choices and resource
  trade-offs. Verification planning and independent reviews provide early
  feedback to assess and refine those choices as the design evolves.
- **Requirements-driven verification.** Original requirements and independent
  references guide testpoints, reference models and assessment criteria.
  Functional simulation, lint/CDC, synthesis, timing and power analysis check
  behavior and engineering targets. Independent reviews assess whether stimuli,
  observations and checking logic can detect violations and trigger test failure.
- **Diagnosis and coordinated revision.** Executors combine diagnosis with
  change-impact analysis to identify the task responsible for a repair and assess
  its effects on other requirements and artifact consistency. The responsible
  task performs the revision in coordination with affected work.

The workflow engine connects these activities across iterations. It coordinates
execution through artifact dependencies and links checking conclusions to
artifact versions, identifying work that needs reassessment while retaining
passing results that still apply. Artifacts and run records persist in the
module workspace, allowing development to continue across sessions.

Deliverables include specifications, RTL, UVM testbenches, constraints,
synthesized netlists, and verification and analysis reports.

## Requirements

The agent's execution environment needs:

- Python 3.10 or later, with the packages in [requirements.txt](requirements.txt).
- For the full flow, Synopsys SpyGlass, VCS with UVM, Verdi waveform tools,
  Design Compiler and PrimeTime, with the corresponding licenses and cell
  libraries. See [EDA Tool Environment](docs/eda-env.md) for configuration.

You can check tool availability and license readiness with the `env-precheck`
skill in a separate session before starting development.

## Quickstart

1. **Install and enable VeriPower** using your platform's guide:
   [Claude Code](.claude/README.md), [OpenCode](.opencode/README.md),
   [DeepSeek Harness](.dsh/README.md) or [Codex](.codex-plugin/README.md).
   Start a session and ask the agent to list the VeriPower skills to confirm
   that the plugin loaded.

2. **Prepare the original requirements** at `{module_dir}/intent/brainstorm.md`
   and copy referenced material into `{module_dir}/intent/`. Replace
   `{module_dir}` with the absolute path to your module workspace.
   An existing suitable specification can be used directly. If the requirements
   need discussion, use the `brainstorm` skill in a separate session and review
   the resulting document before starting the flow.

3. **Start a new session** with VeriPower enabled and ask:

    > Run the design-flow skill for {module_dir}.

The agent proceeds within your authorization and brings back questions that need
your input. Published artifacts are under `Design/` and `Verification/` in the
module workspace.

## Documentation

- [User Guide](docs/USER-MANUAL.md): prepare inputs, follow progress, review
  results, revise requirements and resume interrupted work.
- [Architecture](docs/ARCHITECTURE.md): development method, task responsibilities
  and coordination across iterations.
- [Contributing](CONTRIBUTING.md): development principles and validation.

**Version:** v0.2.9 · [MIT License](LICENSE) · [Issues](https://github.com/chipweaver/veripower/issues)
