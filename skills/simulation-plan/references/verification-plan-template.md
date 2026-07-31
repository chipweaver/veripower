# `verification-plan.md` template

The section outline for the plan document you author, and the one artifact the user's gate is
held over. The rosters themselves live in the three sidecars: every section here is for what a
per-field schema cannot hold, so a section that restates a table you just authored is a second
copy that will drift.

```markdown
# <module> Verification Plan

## 1. Scope
Module name / Top / spec references.

## 2. Test Strategy
Agent grouping / sequence design / RM type / scoreboard boundary, as narrative. Write why each
boundary falls where it does.

## 3. Testpoints
The testpoints themselves are `tb-scaffold.json`'s `testpoints[]`; do not restate them as a
table. What belongs here is what is not a per-testpoint field: how the testpoints partition the
verification, and which behaviors are deliberately left to downstream stages.

## 4. Power Scenarios
One materialization note per scenario, per `power-scenarios-template.md`: the standard row's
abstract states, what they reduce to on this module, and why a row was materialized that way or
dropped as inapplicable. `power-scenarios.json` carries only the four fields power-analysis
reads, so this section is the sole home for everything else about a scenario.

## 5. Revision Summary
Append on a scoped revision when a real diff is present: trigger context + revision highlights.

## Document Control
```
