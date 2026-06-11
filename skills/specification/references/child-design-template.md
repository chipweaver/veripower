# child-design template

Every sub-design file `{workdir}/<child>.md` follows this structure (Surface 1 contract, English canonical section headings; prose body is Surface 2 — bilingual allowed).

## Frontmatter (required)

```yaml
---
child: <child_name>                # required; equals manifest.children[].name
parent: <module_name>              # required
brainstorm_anchor: "lines X-Y"     # required; or "lines X-end" / "lines X-Y, X'-Y'" / "D4-architecture-only"
ports:                             # required (may be empty). cross-out ports only
  - <port_name>                    #   each must appear in main §1.4.1 ∪ §1.4.2
clocks:                            # required (may be empty)
  - { name: <clock_name>, domain: <domain> }    #   each name must appear in main §1.6
features:                          # required (may be empty)
  - <feature_id>                   #   each must appear in main §1.3
---
```

## §1 Purpose

≤30 lines. Child role + context + implementation-strategy choice.

## §2 Interface

Detailed port table (covers frontmatter `ports` with detailed signal direction / width / clock domain / protocol / timing semantics). Child-internal-only boundary ports (test-mode strobe / debug tap / internal handshake) appear here too but are NOT in frontmatter `ports`.

## §3 Internal Behavior

Register side effects / FSM / reset behavior / clock-gating logic (prose + tables).

## §4 Corner Cases

Async interaction / back-pressure / error handling / exception paths (prose).

## §5 Verification Hints (9 columns required)

| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |
|---------|---------------|----------------------|------------------------------|------------------|------------|---------------|---------|---------------|
| CHK-... | F-... | (≤20-word summary) | (brainstorm verbatim RTL formula / token, MUST contain `assign / always / <= / literal numeric` or marked `(narrative-only; see L<N>-<M>)`) | L<N> or §subsection-anchor | <observable signal> | <RM rule> | ≤N cycle | <reset value> |

**Critical**: `ImplementationDetailVerbatim` is the **only** source of cycle-accurate refmodel formulas for downstream simulation-plan / simulation. It must preserve brainstorm-original tokens (not summary-compressed). `check_coverage.py`'s token-survival check requires every brainstorm hard token (`assign` / `always` / sized literals / timing) to survive into `design.md ∪ <child>.md`, so brainstorm formulas land here verbatim.
