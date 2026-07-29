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
soft hint; the hard guarantee is `check-coverage`'s purity gate.

## Write
- `manifest.json` — `module`; `children[]` with `name` / `doc` / `rtl_modules[]` (REQUIRED, ≥1) /
  `brainstorm_anchor` / `role`; optional `shared_subsections[]`.
- `design.md` §1.1–1.7 overview (narrative only; each section points at its sidecar), per
  `references/design-template.md`. §1.3 / §1.5 / §1.6 carry narrative — and, for §1.5, the
  waveform diagrams — plus a pointer to `features.json` / `timing-scenarios.json` /
  `clocks.json`; §1.4.1 / §1.4.2 point at `top-io.json` / `interconnects.json`; §1.2 keeps the
  architecture diagram and §1.7 points at `manifest.json`. **No feature, scenario, clock,
  port, interconnect or submodule table** — you are writing the manifest and the sidecars, so
  a table here would be a second hand-written home for fields you just authored.
- `ppa.json` — the D6 `ppa_targets` **verbatim** as a JSON array of `{dim, target}` (`[]` when D6
  declares none or was not reached).
- `top-io.json` — one object per top-level port (`name` / `direction` / `width` / `clock_domain` /
  `interface_group` / `role`; an output also declares `owner`; a reset also declares
  `reset_polarity` / `reset_kind`), per `references/top-io.schema.json`.
- `interconnects.json` — one object per cut edge (`wire` / `producers` / `consumers` / `width` /
  `clock_domain`), per `references/interconnects.schema.json`. `[]` for an N=1 module.
- `timing-scenarios.json` — one object per scenario (`id` / `stimulus` / `expected` /
  `timing_constraint`, plus optional `interface_mode` / `exceptions`), per
  `references/timing-scenarios.schema.json`.
- `features.json` — one object per feature (`id` / `name` / `description` / `mode_interface` /
  `priority` / `happy_path` / `corner_cases` / `negative_cases`, plus optional
  `coverage_intent`), per `references/features.schema.json`. Every field except
  `coverage_intent` must be non-empty — a blank one is a defect, not a default.
- `clocks.json` — one object per clock (`name` / `freq_mhz` / `period_ns` / `relationship`, plus
  optional `generated` / `role`), per `references/clocks.schema.json`. Numbers are numbers;
  exactly one `relationship: "primary"`; a mistyped key fails at `derive-constraints`.

## Output
End with `STATUS: DONE` + the written paths, or `STATUS: BLOCKED <reason>` (a program exception
prevented writing — never a logic decision).
