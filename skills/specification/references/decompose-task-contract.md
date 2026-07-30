# Spec decompose sub-Task contract (Wave 1)

Partition the module from the frozen `<brainstorm>/brainstorm.md` and author the `design.md`
overview. Do not call the Task tool.

## Read
`<brainstorm>/brainstorm.md` (frozen, `Status: approved`) — the module set (**D4**) and the
inter-module wire list (**D2b** → `interconnects.json`) are the partition inputs.

## Partition strategy
Partition on the interface graph's edges, NOT by line counts: cut ONLY at clean elastic-handshake
boundaries (`valid/ready` or `req/ack`); a skew- or phase-locked coupling is never a cut point — the
modules it binds stay in one child, internalizing that coupling. Each child is thus one or more
whole RTL modules forming a coupling cluster bounded by clean handshakes; a tightly-coupled fabric
with no clean internal handshake is monolithic (N=1 — only the top boundary is clean). Small leaf
modules join their cluster — no line-count floor / size class.

**top-integration carve-out (best-effort hint):** `<TOP>` (= `manifest.module`) should form its own
child whose `rtl_modules == [<TOP>]` — do not bundle any logic module into the top child. This is a
soft hint; the hard guarantee is `derive-ports`' purity check at the partition gate.

## Write
- `manifest.json` — `module`; `children[]` with `name` / `doc` / `rtl_modules[]` (REQUIRED, ≥1) /
  `brainstorm_anchor`. The anchor is free text that locates this child's primary passage in
  **this** brainstorm — a heading, a candidate name, a quoted phrase, a line range, whatever
  actually points there. No script parses it and no format is imposed: a brainstorm's shape is
  the dialogue's to choose. Its one reader is that child's spec reviewer, who reads the whole
  document anyway and uses the anchor only to know where to start.
- `design.md` §1.1–1.7 overview (narrative only; each section points at its sidecar), per
  `references/design-template.md`. §1.3 / §1.5 / §1.6 carry narrative — and, for §1.5, the
  waveform diagrams and the scenario rows — plus a pointer to `features.json` /
  `clocks.json`; §1.4.1 / §1.4.2 point at `top-io.json` / `interconnects.json`; §1.2 keeps the
  architecture diagram and §1.7 points at `manifest.json`. **No feature, scenario, clock,
  port, interconnect or submodule table** — you are writing the manifest and the sidecars, so
  a table here would be a second hand-written home for fields you just authored.
- `ppa.json` — the D6 `ppa_targets` **verbatim** as a JSON array of `{dim, target}` (`[]` when D6
  declares none or was not reached).
- `top-io.json` — one object per top-level port (`name` / `direction` / `width` / `clock_domain` /
  `interface_group` / `role`; a reset also declares `reset_polarity` / `reset_kind`), per
  `references/top-io.schema.json`.
- `interconnects.json` — one object per cut edge (`wire` / `producers` / `consumers` / `width` /
  `clock_domain`), per `references/interconnects.schema.json`. `[]` for an N=1 module.
- `features.json` — one object per feature (`id` / `name` / `description` required; the rest
  of `references/features.schema.json` describes the shape a feature record usually takes —
  write the ones this feature actually has).
- `clocks.json` — one object per clock (`name` / `period_ns` / `relationship`, plus optional
  `generated` / `role`), per `references/clocks.schema.json`. `period_ns` is the sole statement
  of the clock's rate — numbers are numbers; exactly one `relationship: "primary"`; a mistyped
  key fails at `derive-constraints`.

## Output
End with `STATUS: DONE` + the written paths, or `STATUS: BLOCKED <reason>` (a program exception
prevented writing — never a logic decision).
