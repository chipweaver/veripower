<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-text-dark.png">
    <img alt="VeriPower" src="assets/logo-text-light.png" width="320">
  </picture>
</p>

<h3 align="center">An open-source agent flow for front-end chip design</h3>

<!-- <p align="center"><a href="">Paper</a></p> -->

---

VeriPower is an open-source agent flow that takes a natural-language spec all the way to front-end signoff on commercial EDA tools. A deterministic engine sits underneath, recording every action in an append-only log. All pipeline status is derived from that log on demand, never stored as a flag or snapshot. The agent can iterate on its own, but every LLM-authored oracle needs a human sign-off.

Ships as a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin.

## How it works

A deterministic engine owns the facts. Agents and humans are proposers. The engine keeps an append-only record of every action and conclusion, and whether a stage is done, stale, or failed gets computed from that record each time you ask. An orchestrator queries the engine for one action, carries it out, queries again. No state carried between queries.

<p align="center">
  <img src="assets/architecture.png" alt="VeriPower architecture" width="460" />
</p>

Every verification conclusion is fingerprinted against the content it consumed and produced. Edit something upstream and the downstream conclusions go invalid on the next query. Design and verification both start from the spec but then diverge, so the reference model is derived from the spec, not from the implementation. EDA tool verdicts are authoritative. LLM-authored oracles are good enough for iteration but need human endorsement for signoff, and that endorsement lapses if the oracle content changes.

More in [ARCHITECTURE.md](ARCHITECTURE.md) ([中文](ARCHITECTURE.zh.md)).

## Pipeline

Eight stages, spec through power analysis. The dependency graph falls out of each rule's artifact declarations.

<p align="center">
  <img src="assets/pipeline-dag.png" alt="Pipeline dependency graph" width="660" />
</p>

Reference implementation wraps Synopsys tools (SpyGlass, Design Compiler, PrimeTime, VCS+UVM). Each stage is a self-contained skill, so you can swap one (Verilator for simulation, Yosys for synthesis) without touching the rest.

## Results

Three front-end design tasks, bare Claude Code vs. Claude Code + VeriPower. Same LLM, same spec, same EDA tools. Paper forthcoming.

| Benchmark | Scale | Baseline | + VeriPower |
|---|---|---|---|
| gateGPT — fixed-point GPT inference | 346K gates | 3 of 4 coverage metrics below 90% | **pass** |
| FSA — FlashAttention accelerator | 32K gates | 2 unresolved CDC violations | **pass** |
| Coral-NPU — RISC-V ML accelerator | 3.4M gates | 6/19 tests | **19/19** |

Bare agents write correct RTL but can't catch their own blind spots when testing it.

## Quickstart

```bash
claude plugin marketplace add chipweaver/veripower
claude plugin install veripower@chipweaver
```

Or point at a working copy: `claude --plugin-dir /path/to/veripower`.

Run the `brainstorm` skill to settle requirements first, then tell the agent:

> Run the design flow for {module_dir}

Full walkthrough in the [user manual](docs/USER-MANUAL.md) ([中文](docs/USER-MANUAL.zh.md)).

**Requirements.** Python 3, `jsonschema`, `referencing`. Synopsys EDA tools, swappable per skill.

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

**Status:** alpha (v0.1.7). [MIT License](LICENSE). [Contributing](CONTRIBUTING.md). [Issues](https://github.com/chipweaver/veripower/issues).
