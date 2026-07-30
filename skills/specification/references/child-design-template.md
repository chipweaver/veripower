# child-design template

Every sub-design file `{workdir}/<child>.md` follows this structure (Surface 1 contract, English canonical section headings; prose body is Surface 2, bilingual allowed).

## Frontmatter (required)

```yaml
---
ports:                # required (may be empty). Cross-out ports only; each must appear in top-io.json ∪ interconnects.json
  - <port_name>
clocks:               # required (may be empty). Each must appear in clocks.json
  - <clock_name>
features:             # required (may be empty). Each must appear in features.json
  - <feature_id>
---
```

Three keys, all of them claims about which shared thing is yours. Your name and your parent's
are in `manifest.json` already — do not restate them here.

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

If you drive a top-IO **output**, list it in your frontmatter `ports` — that claim is the only record of who drives it, and `check-coverage` fails an output no child claims. Prefer driving it from a leaf child passed through the pure top over top-level glue. Which **inputs** you read is your own decision, declared in your frontmatter and nowhere else.

## §3 Internal Behavior

Register side effects / FSM / reset behavior / clock-gating logic (prose + tables).

## §4 Corner Cases

Async interaction / back-pressure / error handling / exception paths (prose).

## §5 Verification Hints

The hints live in `check-hints/<child>.json`, one file per child because children are authored
in parallel. Keep this section as a pointer to it; narrative about *why* a check exists belongs
in §3 / §4.

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
