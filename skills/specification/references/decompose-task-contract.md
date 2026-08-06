# Spec decompose sub-Task contract (Wave 1)

Partition the module from the frozen `<brainstorm>/brainstorm.md` and author the `design.md`
overview. Do not call the Task tool: a sub-Task writes no events, so anything you dispatch is
work the kernel cannot see or audit.

## Read
`<brainstorm>/brainstorm.md` (frozen for the run) — the module set (**D4**) and the
inter-module wire list (**D2b** → `interconnects.json`) are the partition inputs.

## Partition strategy
Partition on the interface graph's edges, NOT by line counts: cut ONLY at clean elastic-handshake
boundaries (`valid/ready` or `req/ack`); a skew- or phase-locked coupling is never a cut point — the
modules it binds stay in one child, internalizing that coupling. Each child is thus one or more
whole RTL modules forming a coupling cluster bounded by clean handshakes; a tightly-coupled fabric
with no clean internal handshake is monolithic (N=1 — only the top boundary is clean). Small leaf
modules join their cluster — no line-count floor / size class.

**top-integration carve-out (best-effort hint):** `<TOP>` (= `manifest.module`) should form its own
child whose `rtl_modules == [<TOP>]` — do not bundle any logic module into the top child. It is checked at the partition gate.

## Write
Each sidecar's fields and which of them are required are in its own
`references/<name>.schema.json`; read that rather than a list here.

- `manifest.json` — `module`, plus `children[]` with `name` / `doc` / `rtl_modules[]` (≥1) /
  `brainstorm_anchor`. The anchor is free text locating this child's primary passage in **this**
  brainstorm — a heading, a candidate name, a quoted phrase, a line range, whatever actually
  points there. No script parses it; its one reader is that child's spec reviewer, who reads the
  whole document anyway and uses the anchor only to know where to start.
- `design.md` §1.1–1.7 overview, per `references/design-template.md`: §1.2 the architecture
  diagram, §1.5 the waveforms and scenario rows, §1.7 a pointer to `manifest.json`, and each of
  §1.3 / §1.4.1 / §1.4.2 / §1.6 the narrative its sidecar cannot hold.
- `ppa.json` — the D6 `ppa_targets` **verbatim** (`[]` when D6 declares none or was not reached).
- `top-io.json` — one object per top-level port.
- `interconnects.json` — one object per cut edge; `[]` for an N=1 module.
- `features.json` — one object per feature.
- `clocks.json` — one object per clock. `period_ns` is the sole statement of the clock's rate,
  and exactly one entry is `relationship: "primary"` — the schema cannot express that, so
  `derive-constraints` fails loud on it.

## Output
End with `STATUS: DONE` + the written paths, or `STATUS: BLOCKED <reason>` (a program exception
prevented writing — never a logic decision).
