# Spec decompose sub-Task contract

Author `design.md` and the boundary sidecars from `{workdir}/requirements.json`.
Do not call the Task tool: a sub-Task writes no events, so anything you dispatch is work the kernel
cannot see or audit.

## Read
`{workdir}/requirements.json`, all of it: the engineer's requirements, one row each, with `judge`
naming who establishes it. It is the only statement of intent you have; the intent document itself
is not yours to read. A row that points at a file under `<intent>/` — a register map, an
interface list, a reference model — is read there when the boundary you author depends on it. Rows
judged by `specification` are yours to realize: a clock, a port, the top module's name, an SDC
statement. Rows the engineer wrote about the architecture constrain what you argue for below.

## What you decide, and what you do not
You freeze the **boundary**: the top module's name, the clocks and their budgets, every top-level
port, the obligations more than one part must jointly keep at that boundary, and the timing
scenarios. Everything downstream is held to those.

**Which RTL modules exist is not yours to fix.** `design.md` §1.2 argues for a structure — where a
clean elastic handshake (`valid/ready`, `req/ack`) admits a cut, where a skew- or phase-locked
coupling forbids one, which block carries the dominant area term — and whoever writes the RTL reads
that argument and decides. Naming a roster instead would bind an implementer to a split chosen
before anyone had the RTL in front of them, and the sidecars carry no field for one.

## Write
Each sidecar's fields and which of them are required are in its own
`references/<name>.schema.json`; read that rather than a list here.

- `manifest.json` — `module`, the top RTL module's name, and nothing else.
- `design.md` per `references/design-template.md`: the architecture it proposes and why, the
  boundary narrative, the joint obligations, the waveforms and scenario rows. It records
  decisions; a requirement is cited by row id, never restated.
- `top-io.json` — one object per top-level port.
- `clocks.json` — one object per clock. `period_ns` is the sole statement of the clock's rate
  and `io_delay_ns` of its ports' arrival budget; both are numbers you state, and both decide
  what synthesis and timing-analysis judge, so a row that gives one is cited and one the
  engineer left open goes to the human at the gate rather than to a default. Exactly one entry
  is `relationship: "primary"` — the schema cannot express that, so `derive-constraints` fails
  loud on it.

## Output
End with `STATUS: DONE` + the written paths, or `STATUS: BLOCKED <reason>` (a program exception
prevented writing — never a logic decision).
