# VeriPower

VeriPower provides a shared IC design workflow with independent stage skills.
Read CONTRIBUTING.md for development principles and validation, and ARCHITECTURE.md
for the runtime model. Existing code and documentation are open to correction.

## Runtime boundaries

- `framework/scripts/kernel.py` owns the module's append-only `events.jsonl`, dispatch,
  outcome collection, decisions and signoff. `decide` derives the next action from events
  and current artifact fingerprints; `status` is read-only.
- `framework/scripts/rules.py` declares stage inputs, directory roots and execution placement.
  These declarations define dependencies and legal repair owners, including the failed stage.
  Each stage's `result.json` lists the outputs delivered by that run.
- `framework/scripts/facts.py` computes validity and signoff readiness;
  `schedule.py` selects work; `store.py` handles artifacts and event storage.
- `skills/design-flow/SKILL.md` defines orchestration and applies the task's actual
  authorization to decisions. Platform adapters provide native tool integration and preserve
  host permissions.

`signoff` records acceptance when the task calls for it, after checking current proofs.
`provenance` and `reason` identify the decision maker, authorization and basis. The record
applies to the accepted evidence; readiness alone does not record acceptance.

## Stage artifacts

Each module holds `intent/`, `Design/`, `Verification/` and `events.jsonl`. Stages obtain input
locations from their dispatch, write within their workdir and close through their own CLI.
The intent tree contains the original requirements and referenced authorities. Readers may
consult it to resolve discrepancies in derived documents.

Specification owns requirements, design choices and interface/clock boundaries. RTL design owns
the module split and implementation. Verification derives expected behavior from independent
requirements; implementation evidence may support diagnosis. Stage owners assess review findings
and resolve demonstrated defects before acceptance.

Schemas under `framework/references/schemas/` and each skill's references define the machine
interfaces. Skill references contain stage-specific tool and authoring guidance.

`brainstorm` and `env-precheck` are pre-pipeline skills. They neither close stages nor write
kernel events. Installation and platform usage are described in README.md and adapter guides.
