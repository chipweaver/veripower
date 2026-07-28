# child-design template

Every sub-design file `{workdir}/<child>.md` follows this structure (Surface 1 contract, English canonical section headings; prose body is Surface 2, bilingual allowed).

## Frontmatter (required)

```yaml
---
child: <child_name>                # required; equals manifest.children[].name
parent: <module_name>              # required
brainstorm_anchor: "lines X-Y"     # required; or "lines X-end" / "lines X-Y, X'-Y'" / "D4-architecture-only"
ports:                             # required (may be empty). cross-out ports only
  - <port_name>                    #   each must appear in main §1.4.1 ∪ §1.4.2
clocks:                            # required (may be empty)
  - { name: <clock_name>, domain: <domain> }    #   each name must appear in clocks.json
features:                          # required (may be empty)
  - <feature_id>                   #   each must appear in main §1.3
---
```

## §1 Purpose

≤30 lines. Child role + context + implementation-strategy choice.

## §2 Interface

A detailed port table covering the frontmatter `ports` (per-signal direction, width, clock domain, protocol, timing semantics). Child-internal-only boundary ports (test-mode strobe, debug tap, internal handshake) also appear here, though they are not in the frontmatter `ports`.

Each of the following **restates its single source verbatim; never introduce a divergent value**:
- **Inter-module port** (a §1.4.2 wire): width and clock domain match the §1.4.2 row.
- **Control/status inter-module port**: its **Encoding** (bit/field→symbol meaning plus per-code consumer obligation) matches the §1.4.x row.
- **Inter-module behavior contract** (a shared operating-phase / sequencing / co-assertion contract, declared in the §1.4.2.1 companion): reference the companion's declared names; do not redefine the phase set or sequencing.

A top-IO **output** is owned by exactly one child (listed in that child's frontmatter `ports`); a leaf child passed through the pure top is preferred.

## §3 Internal Behavior

Register side effects / FSM / reset behavior / clock-gating logic (prose + tables).

## §4 Corner Cases

Async interaction / back-pressure / error handling / exception paths (prose).

## §5 Verification Hints (9 columns required)

| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |
|---------|---------------|----------------------|------------------------------|------------------|------------|---------------|---------|---------------|
| CHK-... | F-... | (≤20-word summary) | (brainstorm verbatim RTL formula / token, MUST contain `assign / always / <= / literal numeric` or marked `(narrative-only; see L<N>-<M>)`) | L<N> or §subsection-anchor | <observable signal> | <RM rule> | ≤N cycle | <reset value> |

**Critical**: `ImplementationDetailVerbatim` is the **only** source of cycle-accurate refmodel formulas for downstream simulation-plan / simulation. It must preserve brainstorm-original tokens (not summary-compressed). `check-coverage`'s token-survival check requires every brainstorm hard token (`assign` / `always` / sized literals / timing) to survive into `design.md ∪ <child>.md`, so brainstorm formulas land here verbatim.
