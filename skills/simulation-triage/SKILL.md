---
name: simulation-triage
description: Diagnose a failed verification run from requirements, implementation and experimental evidence, and identify the repair owner; not for editing canonical design or verification artifacts.
---

# Simulation Triage

Determine what failed, why, and who can repair it. Treat supplied labels and attributions as
hypotheses to check. Read `{workdir}/dispatch.json` for input locations. `sim_run` names the failed
run itself; inspect its result, logs, TB, coverage and any retained waveform rather than a later
canonical result. `intent`, `requirements`, `design`, `plan` and `rtl` provide the other evidence.

Read the material needed to resolve the question, including tool scripts when relevant. Keep
canonical inputs unchanged; write diagnostics and experiments under `{workdir}`. Attribute causes
from the evidence, including local simulation defects.

## Investigate

Form a concrete hypothesis from the requirement and observed behavior. Check the implementation,
stimulus, observation and expected result. A reference model must derive its expected behavior
from an independent task authority; disagreement with the current plan can expose a plan defect.

Use retained waveforms when useful. Passing simulation tests normally discard their FSDB, so a
coverage failure may need a focused rerun to observe the relevant behavior. Discover actual signal
paths from the TB and design. For the supplied fsdbreport tool, query one signal per invocation:
it retains only the last `-s`, and its paths are slash-form rooted at the testbench.
An unmatched path can return exit code 0 with an empty report; inspect the warning before interpreting that as missing waveform data.

```bash
fsdbreport <waveform.fsdb> -s /<actual-signal-path> -bt <t0> -et <t1> -of h -o experiment/window.txt
```

If the existing evidence is insufficient, build a focused experiment under `experiment/`. Use the
unchanged implementation for claims about the failure; if varying something to test a hypothesis,
state what changed and what that comparison can establish. Keep commands, inputs and results.
A failed attempt to reach behavior does not prove it unreachable; approval does not supply that
proof either. Distinguish a technical evidence gap from an acceptance decision needing authorization.

## Return the diagnosis

Submit the diagnosis object described by [result.schema.json](references/result.schema.json)
to the CLI, which validates it and writes `result.json`:

```bash
python3 <skill>/scripts/simtriage/__main__.py finalize --workdir {workdir} --json-stdin
```

`<skill>` is this skill's directory. Each supported finding identifies its `root_cause` repair stage,
`anchor` and `reason`. The owner can be `simulation` itself. Separate independently supported causes;
do not invent an owner to obtain a route. If evidence cannot settle attribution, leave `findings`
empty and explain the missing evidence in `reason`. This completed diagnosis returns the unresolved
decision to the caller; it does not request another identical investigation.

Finalize validates the diagnosis structure and preserves `experiment/`; it does not prove the
reasoning. Return `STATUS: DONE` when the diagnosis is written, including an explicit unresolved
attribution. Return `STATUS: BLOCKED <cause>` if you could not produce it. Do not invoke kernel
state transitions or edit another stage's outputs.
