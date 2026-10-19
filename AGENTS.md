# VeriPower

VeriPower is a host-neutral IC design workflow plugin with independent stage skills.
This file guides development of the plugin repository. Existing code and documentation
are open to correction.

## Task references

- For repository changes, follow [CONTRIBUTING.md](CONTRIBUTING.md) for development and validation.
- For scheduling, artifact provenance or acceptance changes, consult
  [the architecture](docs/ARCHITECTURE.md) and [the framework guide](framework/README.md)
  for the runtime model and implementation entry points.
- For stage changes, inspect `skills/<stage>/SKILL.md`, its scripts and relevant references together.
  Shared machine interfaces live in `framework/references/schemas/`.
- For installation and platform integration, use [README.md](README.md) and the relevant adapter guide.

Instructions needed to execute an installed skill belong in the skills and adapters, so execution
works without this repository's AGENTS.md or the author's session context.

## Runtime boundaries

- `framework/scripts/kernel.py` owns the module's append-only `events.jsonl`, dispatch and
  outcome collection, and records decisions and signoff. Kernel commands, including queries,
  remove owner-write permission from `intent/` to protect source materials from incidental writes.
- `framework/scripts/rules.py` declares stage inputs, directory roots and execution placement.
  These declarations define dependencies and legal repair owners, including the failed stage.
- `skills/design-flow/SKILL.md` defines orchestration and applies the task's actual
  authorization to decisions. Platform adapters provide native tool integration and preserve
  host permissions.

`signoff` records acceptance when the task calls for it, after checking current proofs.
The record applies to the accepted evidence; readiness alone does not record acceptance.

## Stage boundaries

Stages own their workdir artifacts and close through their own CLI; the kernel publishes
the outputs declared in each run's `result.json`. The module's `intent/` tree contains the
original requirements and referenced authorities used to resolve discrepancies in derived documents.

Specification owns requirements, design choices and interface/clock boundaries. RTL design owns
the module split and implementation. Verification derives expected behavior from independent
requirements; implementation evidence may support diagnosis. Stage owners assess review findings
and resolve demonstrated defects before acceptance.

`brainstorm` and `env-precheck` are pre-pipeline skills. They neither close stages nor write
kernel events.
