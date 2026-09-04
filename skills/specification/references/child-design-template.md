# child-design template

Every sub-design file `{workdir}/children/<child>.md` follows this structure (Surface 1 contract, English canonical section headings; prose body is Surface 2, bilingual allowed).

## Frontmatter (required)

```yaml
---
ports:                # required (may be empty). Cross-out ports only; each must appear in top-io.json ∪ interconnects.json
  - <port_name>
clocks:               # required (may be empty). Each must appear in clocks.json
  - <clock_name>
---
```

Two keys, both claims about which shared boundary is yours; the rtl-design child author reads them
to know which ports it declares. Your name and your parent's are in `manifest.json` already — do
not restate them here.

## §1 Purpose

≤30 lines. Child role + context + implementation-strategy choice, citing the `requirements.json`
rows this child realizes by id. A requirement is stated once, in the ledger; here you decide, and
point at what you decided for.

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

If you drive a top-IO **output**, list it in your frontmatter `ports` — that claim is the only record of who drives it, and `check-crossrefs` fails an output no child claims. Prefer driving it from a leaf child passed through the pure top over top-level glue. Which **inputs** you read is your own decision, declared in your frontmatter and nowhere else.

## §3 Internal Behavior

Register side effects / FSM / reset behavior / clock-gating logic (prose + tables).

## §4 Corner Cases

Async interaction / back-pressure / error handling / exception paths (prose).

## §5 Verification Hints

The hints live in `check-hints/<child>.json`, one file per child because children are authored
in parallel; the contract is `wave2-check-hints-contract.md` and the shape
`check-hints.schema.json`. Keep this section as a pointer to it; narrative about *why* a check
exists belongs in §3 / §4, and a hint that has to observe an internal signal says here why the
boundary does not suffice.
