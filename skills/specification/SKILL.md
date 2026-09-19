---
name: specification
description: Establish requirements, design decisions, interfaces, clocks and constraints from the delivered intent, or revise them after evidence-based clarification; not for implementing RTL or verification.
---

# Specification

Establish the task's requirements and implementation boundary from the original intent. Read
`{workdir}/dispatch.json`; `intent` names the delivered material and its referenced authorities.
Read the evidence needed to resolve a question. Write this stage's artifacts under `{workdir}`.
Author directly or delegate focused work, retaining responsibility for the resulting decisions.

## Establish or revise the definition

Continue from existing artifacts. Use changed inputs, failure records and actual user decisions
to scope work; absence of `caused_by` does not imply a first delivery. Preserve unaffected content
and stable requirement IDs. Read an upstream request's evidence before accepting its attribution.

Produce the requirements ledger using [ledger-task-contract.md](references/ledger-task-contract.md)
and the boundary using [decompose-task-contract.md](references/decompose-task-contract.md).
`design.md` records design choices and joint obligations; the RTL author decides the module split.
The boundary sidecars are `manifest.json`, `clocks.json` and `top-io.json`; their formats are in the
corresponding reference schemas.

Check the ledger:

```bash
python3 <skill>/scripts/spec/__main__.py check-ledger --workdir {workdir}
```

`<skill>` is this skill's directory. The output shows unresolved/unassignable, outside-scope and
rows requiring decisions, plus numerical targets. Resolve these according to the task and actual
authorization. Explain choices requiring a human decision before seeking it; act within an existing
delegation when permitted. Record material decisions and their basis in `spec-review/decisions.md`,
identifying who decided and under what authorization. An agent decision is not a user quotation.

Distinguish a mistaken transcription or design assumption from a proposed change to acceptance.
Correct the former from source evidence. A genuine acceptance change needs authorization and a
clear account of what is no longer being claimed. Neither an approval nor a decision record proves
reachability, physical feasibility or successful verification. Investigate factual questions or
return them to the responsible stage rather than redefining a requirement to make a result pass.

## Complete and review

Use [check-hints-task-contract.md](references/check-hints-task-contract.md) to describe the
observations used by simulation. Check the ledger/boundary/hint references and derive constraints:

```bash
python3 <skill>/scripts/spec/__main__.py check-crossrefs --workdir {workdir}
python3 <skill>/scripts/spec/__main__.py derive-constraints --workdir {workdir}
```

These checks identify inconsistent references and invalid tool inputs; they do not establish the
truth of an engineering assumption. Repair the side that is wrong based on evidence.

Have the complete delivery independently reviewed using
[review-task-contract.md](references/review-task-contract.md). Assess findings against their sources,
repair defects, and recheck affected artifacts. Have substantive changes reassessed. Retain the
review and material decisions; assess acceptance impact independently of a finding's label.
Present `design.md`, review paths and any unresolved decision to the user as needed.

## Close

Finalize when this stage's work is complete or an unresolved issue must return to the caller:

```bash
python3 <skill>/scripts/spec/__main__.py finalize --workdir {workdir} \
  [--fail-reason "<unresolved cause and evidence>"]
```

Finalize checks current references, derives constraints, validates the ledger and rejects unresolved
`unassignable` rows. It does not adjudicate review prose. Supply `--fail-reason` for an unresolved
blocking issue or incomplete review; `stage_specific.fail_reason` carries that cause.

Exit 0 means `result.json` was written, pass or fail; return `STATUS: DONE` and let the caller route
it. A nonzero exit means closure failed; resolve the cause or return `STATUS: BLOCKED <cause>`.
