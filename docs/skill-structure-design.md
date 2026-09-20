# Skill and reference organization

This guide describes where stage instructions and shared contracts belong.
For the execution model, see [Architecture](../ARCHITECTURE.md). General
contribution guidance is in [Contributing](../CONTRIBUTING.md).

## Skill responsibilities

A stage skill describes its task, the inputs it receives, the artifacts it
produces, the judgments it must make, and how it closes the run. The dependency
graph comes from the input declarations in `rules.py`, and the engine selects
the next stage. Keep cross-stage scheduling in `design-flow` and the engine.

A failed stage can report a repair owner with the supporting evidence. The
engine checks whether that owner is the failed stage itself or an upstream
input producer. Diagnostic tasks and later decisions can supply or revise an
attribution.

Some stages coordinate authoring and review subtasks as part of their own work.
Their skills should explain that coordination where it is needed. The stage's
execution placement is declared in the rule registry, and platform integration
translates the shared tool calls to the host's execution facilities.

## Writing the entry point

Use the skill's frontmatter to identify when it applies. In the body, introduce
the task and the information needed to begin, then organize the instructions
around the work the executor must perform. Explain the output and closure
requirements where the executor will use them.

Section names should fit the task. There is no required sequence of headings
such as `Iron Rule`, `Artifacts`, or `Return Contract`. Important boundaries
should appear before the work that depends on them, and detailed references
should be linked at the relevant step.

A skill should be usable from an installed plugin without the author's session
history. Resolve bundled resources from the skill directory and write project
artifacts to the assigned work directory. Keep host-specific execution syntax
in platform integration.

## Choosing a home for supporting material

| Location | Content |
|---|---|
| `skills/<stage>/SKILL.md` | Task instructions and links needed to execute the stage |
| `skills/<stage>/references/` | Stage-specific schemas, authoring guidance, review contracts, and templates |
| `skills/<stage>/scripts/` | Stage implementation and command-line helpers |
| `framework/references/` | Contracts and handoff material shared across stages and the orchestrator |
| Project documentation | Explanations for users and contributors |

Keep short guidance in the skill when it is needed throughout the task. Move a
topic to a reference when it has its own readers or can be consulted separately.
A contract consumed by several stages belongs in a shared location.

Use one maintained definition for each rule. A field's schema, a command's
`--help`, or the responsible skill may be the appropriate home. Other readers
should link to that definition rather than maintain another copy.

Small sets of stage-private references can use a flat directory. Shared
references are grouped by function, including `schemas/`, `schemas/events/`,
and `prompts/` under `framework/references/`. Choose directory structure for
the material it contains rather than applying a flat-directory rule to both.

## Naming and links

Use descriptive filenames. Markdown references generally use kebab-case,
Python modules use snake_case, and suffixes such as `.schema.json`,
`-template.md`, and `-task-contract.md` identify a file's purpose.

Refer to another executable skill by its `veripower:` name, for example
`veripower:simulation-plan`. Link to supporting documents where they are read.
Avoid loading another skill's full instructions merely to explain a dependency
already represented by the rule registry. Shared contracts should be referenced
from their common home.

Language conventions are described in [Language conventions](language-posture-design.md).
