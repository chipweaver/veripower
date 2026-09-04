# Spec decompose sub-Task contract (Wave 1b)

Partition the module and author `design.md` and the boundary sidecars from `{workdir}/requirements.json`.
Do not call the Task tool: a sub-Task writes no events, so anything you dispatch is work the kernel
cannot see or audit.

## Read
`{workdir}/requirements.json`, all of it: the engineer's requirements, one row each, with `judge`
naming who establishes it. It is the only statement of intent you have; the intent document itself
is not yours to read. A row that points at a file under `<intent>/` — a register map, an
interface list, a reference model — is read there when the boundary you author depends on it. Rows judged by `specification` are yours to realize in the sidecars: a
clock, a port, a cut edge, an SDC statement. Rows the engineer wrote about the partition or the
architecture constrain what you decide below.

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

- `manifest.json` — `module`, plus `children[]` with `name` / `doc` / `rtl_modules[]` (≥1). `doc`
  is the child's design under `children/`, which leaves this stage as one tree — so how you lay
  the children out inside it is yours, and nothing is lost by it.
- `design.md` per `references/design-template.md`: the architecture diagram, the partition
  rationale, the inter-module behaviour contract, the waveforms and scenario rows, and a pointer
  to `manifest.json`. It records decisions; a requirement is cited by row id, never restated.
- `top-io.json` — one object per top-level port.
- `interconnects.json` — one object per cut edge; `[]` for an N=1 module.
- `clocks.json` — one object per clock. `period_ns` is the sole statement of the clock's rate,
  and exactly one entry is `relationship: "primary"` — the schema cannot express that, so
  `derive-constraints` fails loud on it.

## Output
End with `STATUS: DONE` + the written paths, or `STATUS: BLOCKED <reason>` (a program exception
prevented writing — never a logic decision).
