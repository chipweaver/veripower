# Spec Sidecars → Simulation-Plan Objects

How the specification's authored JSON maps to the objects this stage authors: `agents` /
`sequences` / `tests` / `testpoints[]` / `power_scenarios[]`, and `verification-plan.md`. Each
sidecar's own field semantics live in its schema under `specification/references/`; this guide is
only the mapping.

**Scope boundary.** It stops at the JSON contract you author. Turning the scaffold into
SystemVerilog (driver / monitor bodies, RM `predict()`, scoreboard `check_txn`, reset) happens later
in the `simulation` stage. Do not add SV-rendering
claims here.

`requirements.json` holds what the engineer required, in the engineer's words; `design.md` and the
per-child `<child>.md` hold the decisions made around it. Nothing derives the sidecars — there is
no intermediate cache to read instead of them.

---

## requirements.json → tests

The rows judged by `simulation` are the behaviour the testbench exists to establish; author one
`tests[]` entry per behaviour worth its own testcase, each with its `seqs` and `suites`. The rows
judged by `simulation-plan` are requirements on this plan itself — a stimulus distribution, a seed,
a scope — and the plan reviewer holds the sidecars to them. A test names no requirement: the trace
from a requirement to what verifies it runs row → hint → `testpoints[].covers[]`.

## top-io.json → agents and transactions

- Ports sharing an `interface_group` become one virtual interface and one agent. Grouping is by
  `interface_group`, never by `clock_domain`.
- A group's `direction` values decide the agent's `mode`: `active` for a group you drive, `passive`
  for one you only observe.
- Every `role: "data"` port must end up in exactly one agent, so your `interface_groups` have to
  PARTITION them. check-scaffold enforces it: a group nobody claims would leave those DUT ports
  bound to nothing, which Verilog accepts and VCS compiles without an error.
- clk/rst are the bench's, whichever `interface_group` they carry. An agent whose groups hold
  nothing else has nothing to drive, and is refused.
- You author no signal list. simulation reads this file itself at render time and builds the vif
  signals, the transaction fields, every clock generator and the reset drive from it — same names,
  same widths, verbatim. There is no `addr` / `data` / `rw` to invent, and nothing you write can
  disagree with what specification declared.
- `protocol` is your reference for which sequence pattern to author (`APB3` / `AXI4` / `custom`).

`reset_polarity` reaches the TB, which drives reset and cannot otherwise know which level asserts
it. `reset_kind` / `encoding` are for the specification stage's constraint generation and its
reviewers, not for you.

Every `role: "clock"` port needs a `clocks.json` entry: the primary is the one the agents' vifs
run on, the rest each get their own generator. simulation refuses a clock port with no entry
rather than leaving it out — a DUT clock port nothing binds compiles without an error and stops
that domain for the whole run.

## design.md §1.4 timing scenarios → sequences

One scenario row per `SC-NNN` id, next to the waveform it belongs to. Author one `sequences[]` entry
per id: the row's stimulus is the sequence body, its expected outcome and timing obligation become
the testpoint's check intent, and a negative-path row gets a negative testpoint. The waveform and
its phase-by-phase description carry the cycle-level detail a row cannot.

## check-hints.json → testpoints[].covers[]

One `check-hints.json` file for the module; `check_id` is unique within it. Each hint names the
requirements rows it establishes and says how simulation observes them. You cluster the `check_id`s into
`testpoints[].covers[]` — that clustering is the only authored input here. `simulation` reads each
covered hint, and the rows it names, by id; nothing is copied into the scaffold.

A power bound that names a scenario (`requirements.json` rows judged by `power-analysis` with
`target.scenario`) needs a `power_scenarios[]` entry of that id; check-scaffold refuses the plan
otherwise, because power-analysis would only find out seven stages later.

---

## Worked example: APB slave register module

Given `requirements.json` rows judged by simulation for the APB slave (legal R/W transactions
complete; `pready` inserts wait cycles; illegal address access raises `pslverr`), `top-io.json`
grouping `psel / penable / pwrite / paddr / pwdata / prdata / pready / pslverr` under
`interface_group: APB` (with `pclk` / `preset_n` ungrouped, `role` clock / reset), §1.4 rows
`SC-APB-00` (legal write, `pready` within 1–2 cycles, `pslverr`=0) and `SC-APB-02` (illegal address,
`pslverr` high), and `check-hints.json` with `CHK-APB-00` (write→`reg_file[addr]`,
read→`prdata`) and `CHK-APB-01` (`pslverr <= (addr not in legal_range)`), each naming its rows:

- **agents**: one `apb_agent`, `mode: active`, `interface_groups: ["APB"]`. You write nothing
  else about it: simulation reads the eight APB-group signals out of top-io.json, and `pclk` /
  `preset_n` are the bench's.
- **sequences**: one entry per `SC-NNN` id, each naming `apb_agent`.
- **tests**: one per testcase, each with its `seqs` and its `suites`.
- **testpoints**: a positive one covering `CHK-APB-00` and a negative one covering `CHK-APB-01`.
