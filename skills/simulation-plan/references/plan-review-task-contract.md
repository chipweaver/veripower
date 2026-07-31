# Plan adequacy review sub-Task contract

The simulation-plan main thread dispatches one Level-1 reviewer, AFTER
`simplan check-scaffold` is green and BEFORE the user review loop. You write your findings to a
file; the main thread never re-types them and never reads your body. A human resolves each
blocker at the Step-4 gate. Do not call the Task tool: a sub-Task writes no events, so anything
you dispatch is work the kernel cannot see or audit.

## Inputs (paths only)

- `Design/specification/features.json` — the feature spine testpoints trace to.
- `Design/specification/design.md` (§1 behavior, §1.4 IO/interconnects, §1.5 timing scenarios and
  their waveforms), each `Design/specification/<child>.md`, and each
  `Design/specification/check-hints/<child>.json` — the authoritative statement of what must be
  verified.
- The plan under review: `{workdir}/tb-scaffold.json` — `testpoints[]` (`id` / `intent` / `bins` /
  `covers[]` / `inlined_check_hints[]`) and `skipped_checks[]` — plus `{workdir}/sequences.json`,
  `{workdir}/power-scenarios.json`, and `{workdir}/verification-plan.md` for the strategy behind
  them. The testpoints themselves are in the JSON; the plan md restates none of them.

## Your job: testpoint-adequacy review of the PLAN (NOT TB / RTL / coverage-run)

You are a fresh, skeptical reviewer. **Do not trust that the plan is adequate because the
structural coverage-matrix passed** — that only proves every check_id is covered-or-skipped, not
that the testpoint covering it verifies anything. Two questions, in descending order of what they
cost to find later:

- Does every spec behavior, failure mode, and check Verification Hint have a real testpoint, and
  is every `skipped_checks[]` skip genuinely justified against the spec rather than hiding a
  verification need?
- Does each testpoint's check strategy actually verify the behavior its `intent` promises? A
  `no_predict` or mirror-the-output check can never disagree with the DUT; an assertion can be too
  weak to catch the failure it is aimed at; a testpoint's linked sequences can under-stimulate the
  bound its intent names.

Out of scope: TB materialization and RTL correctness (downstream `simulation` conformance-review
judges TB checks vs testpoints; you judge testpoints vs spec); the structural coverage-matrix
completeness `simplan check-scaffold` already owns; lint / timing / power. If you happen to see
one of those, say so — but as an observation, not as your finding.

## Output: `{workdir}/plan-review/review.md`

Write the file yourself. Free prose, one section per finding, in whatever order serves the reader.
Each finding states three things:

- **What you compared against** — a named `design.md` §ref, a `features.json` id, a `check_id`, or
  nothing (your own judgment). This is the single most useful thing you can tell the human: a
  finding with a frame can be re-checked by anyone; one without it is your opinion, and is
  resolved as such.
- **Blocks or not** — would shipping this plan to `simulation` as-is leave a real behavior
  unverified? Say it plainly. Nothing downstream re-checks testpoint-vs-spec, so a gap you wave
  through here is a gap nobody catches later.
- **Where and what** — the testpoint id (or the plan section, for a gap tied to no single
  testpoint), and one line on what is wrong.

Then end your turn with `STATUS: DONE` and the path you wrote, or `STATUS: BLOCKED <reason>` if
something stopped you from writing it — including a context budget too small to read the whole
plan and spec. Never write a file saying you found nothing when the truth is you could not look.
