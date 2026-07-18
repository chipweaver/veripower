# Spec decompose sub-Task contract (Wave 1)

Partition the module from the frozen `<brainstorm>/brainstorm.md` and author the `design.md`
overview. Do not call the Task tool.

## Read
`<brainstorm>/brainstorm.md` (frozen, `Status: approved`) — the module set (**D4**) and the
inter-module wire table (**D2b** → `design.md` §1.4.2) are the partition inputs.

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
- `design.md` §1.1–1.6 overview (incl. §1.4.1 Top-Level IO + §1.4.2 Inter-module Interconnects) +
  §1.7 submodule index, per `references/design-template.md`.
- `ppa.json` — the D6 `ppa_targets` **verbatim** as a JSON array of `{dim, target}` (`[]` when D6
  declares none or was not reached).

## Output
End with `STATUS: DONE` + the written paths, or `STATUS: BLOCKED <reason>` (a program exception
prevented writing — never a logic decision).
