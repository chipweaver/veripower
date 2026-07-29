# child-design template

Every sub-design file `{workdir}/<child>.md` follows this structure (Surface 1 contract, English canonical section headings; prose body is Surface 2, bilingual allowed).

## Frontmatter (required)

```yaml
---
child: <child_name>                # required; equals manifest.children[].name
parent: <module_name>              # required
ports:                             # required (may be empty). cross-out ports only
  - <port_name>                    #   each must appear in main §1.4.1 ∪ §1.4.2
clocks:                            # required (may be empty)
  - { name: <clock_name>, domain: <domain> }    #   each name must appear in clocks.json
features:                          # required (may be empty)
  - <feature_id>                   #   each must appear in features.json
---
```

## §1 Purpose

≤30 lines. Child role + context + implementation-strategy choice.

## §2 Interface

Your boundary, in whatever shape serves this child. Carry only what is **yours**:

- the net-to-instance.port mapping (which `interconnects.json` wire lands on which port of which instance you wrote);
- bit packing (which field of a wide bus is which);
- per-signal timing semantics at your boundary;
- child-internal-only boundary ports (test-mode strobe, debug tap, internal handshake), which are not in the frontmatter `ports`.

**Do not restate width, clock domain, protocol or encoding.** They live in `top-io.json` / `interconnects.json`; read them there. A restated value is a second hand-written home for one fact, and nothing checks the two against each other.

Two references stay by name rather than by copy:
- **Control/status inter-module port**: its encoding is one `interconnects.json` entry that producer and consumer both read; name the wire, do not re-describe the codes.
- **Inter-module behavior contract** (a shared operating-phase / sequencing / co-assertion contract, declared in the §1.4.2.1 companion): reference the companion's declared names; do not redefine the phase set or sequencing.

A top-IO **output** is owned by exactly one child — `top-io.json`'s `owner` says which, and that child must list the port in its frontmatter `ports`. A leaf child passed through the pure top is preferred. Which **inputs** you read is your own decision, declared in your frontmatter and nowhere else.

## §3 Internal Behavior

Register side effects / FSM / reset behavior / clock-gating logic (prose + tables).

## §4 Corner Cases

Async interaction / back-pressure / error handling / exception paths (prose).

## §5 Verification Hints

The hints live in `check-hints/<child>.md`'s JSON sibling — `check-hints/<child>.json`, one
file per child because children are authored in parallel. Keep this section as a pointer to
it; narrative about *why* a check exists belongs in §3 / §4.

Schema: `references/check-hints.schema.json`. A JSON array, one object per check:

```json
[
  {
    "check_id": "CHK-...",
    "source_feature": "F-...",
    "implementation_detail": "<=20-word summary",
    "implementation_detail_verbatim": "brainstorm-verbatim RTL formula or token",
    "observable": "<observable signal>",
    "reference_rule": "<RM rule>",
    "latency": "<=N cycle",
    "reset_behavior": "<reset value>"
  }
]
```

| Field | Rule |
|---|---|
| `check_id` | Required. Unique across **every** child, not just yours. |
| `source_feature` | Required. A `features.json` `id`. |
| `implementation_detail` / `observable` / `reference_rule` | Required and non-empty. |
| `implementation_detail_verbatim` | Optional in shape, load-bearing in fact — see below. |
| `latency` / `reset_behavior` | Optional. |

**Critical**: `implementation_detail_verbatim` is the **only** source of cycle-accurate refmodel formulas for downstream simulation-plan / simulation. It must preserve the brainstorm's own wording, not a summary of it; when the brainstorm states no formula for a check, say so plainly rather than inventing one. No shape is prescribed — a formula looks however the brainstorm wrote it. What holds this is the spec-review faithfulness lens reading your `<child>.md` against the whole brainstorm: it is the only reader that can tell a compressed paraphrase from the original, and the only one that can tell whether a formula landed in the right child's hint.
