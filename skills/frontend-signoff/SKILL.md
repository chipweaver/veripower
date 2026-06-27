---
name: frontend-signoff
description: Use when all design stages are complete and the module needs its final frontend-signoff checklist, traceability matrix, and evidence package; not for design changes or rerunning prior stages.
---

# Frontend Sign-off

Your sole responsibility: aggregate every upstream `result.json` envelope and evidence path into a sign-off, then compose the human-facing traceability matrix. The pass/fail gate and the `result.json` envelope are owned by the `signoff finalize` verb — never decided by eye, never hand-written.

## When to Use

- All upstream stages are complete and a sign-off output is needed.
- Generate the sign-off checklist and the traceability document.

## Iron Rule

- The gate and the `result.json` envelope are owned by the `signoff finalize` verb. Run it; never re-decide its verdict by eye and never hand-author the JSON.
- Sign-off MUST stand on a fully-passing chain: the script writes `status=fail` (with `fail_reason` listing the failing items) if any upstream envelope is missing / unparseable / not `pass`, any evidence path is unreachable, or specification passed yet its traceability inputs are unreadable.
- `stage_specific` is intentionally an empty object — sign-off content lives in `checklist.md` / `traceability.md`, not in named envelope fields.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |

The script derives the module root (`asic/{module}/`) from `{workdir}` and reads every upstream canonical envelope + evidence path itself; you do not pass them.

### Read by the agent for the traceability matrix (the script does NOT parse these)

| Path | Use |
|---|---|
| `Design/specification/design.md` | §1.3 feature table — the feature axis of the matrix. |
| `Design/specification/manifest.json` | Enumerate `children[]`. |
| `Design/specification/<child>.md` × N | §5 Verification Hints — the check axis of the matrix. |

## Output Artifacts

| Path (relative to `{workdir}`) | Written by | Use |
|---|---|---|
| `result.json` | script | Status contract (`stage_specific` empty; `fail_reason` on fail). |
| `checklist.md` | script | Per-stage pass summary, evidence paths, headline PPA. |
| `traceability.md` | script skeleton + agent | Report/tool-version index (script) + feature→evidence matrix + executive summary (agent). |

## Workflow

Single linear flow (read-only aggregator — every run does identical work, no branch fork).

### Step 1: Run the aggregator

(mandatory; it owns the gate + envelope):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/signoff/__main__.py finalize --workdir {workdir} --module {module}
```

### Step 2: On exit 0

the script has written `result.json` (the authoritative verdict), `checklist.md` (full), and `traceability.md` (skeleton). Read the verdict.
- If `status=fail`, the chain is incomplete; there is nothing to compose — go to step 4.
- If `status=pass`, **compose the traceability matrix** into `traceability.md`: read `manifest.json` + `design.md §1.3` + each `<child>.md §5`, and map every feature/check to the passing evidence that demonstrates it (sim case / timing path / report). Then write the executive summary (cross-stage synthesis: all-pass, N features traced, headline WNS/area/power, coverage, any waivers) and flag anything technically-pass-but-worth-a-human-glance.

### Step 3: On a non-zero exit

the script could not produce a verdict. Emit `STATUS: BLOCKED <one-line reason>` and stop — do not hand-write a `result.json`.

### Step 4: Emit the STATUS line

(see Return Contract).

## Red Flags

| Excuse | Reality |
|---|---|
| "Everything's basically done — sign it off" | You do not decide. `signoff finalize` owns the gate: any upstream not `pass`, any evidence unreachable → it writes `status=fail`. The aggregator does not get to call a stage "close enough" — and neither do you. |

## Completion Gate

- [ ] `signoff finalize` was run; its exit code drove the STATUS branch.
- [ ] On exit 0: `{workdir}/result.json`, `checklist.md`, and `traceability.md` are on disk.
- [ ] On `status=pass`: the feature→evidence matrix and executive summary have been composed into `traceability.md`.
- [ ] No Iron Rule or Red Flag was triggered (no hand-authored envelope, no by-eye verdict).

## Return Contract

As the last line, emit `STATUS: DONE` (when `signoff finalize` wrote `result.json`, i.e. exit 0) or `STATUS: BLOCKED <one-line reason>` (when a non-zero exit / program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
