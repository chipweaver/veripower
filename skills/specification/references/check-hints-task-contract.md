# Check hints

Read requirements.json, top-io.json, design.md and the relevant original sources. Write
check-hints.json using its schema: for each simulation-judged row without a numerical target,
describe the observation and independent expected behavior. The hints together must establish the
whole obligation, including its conditions and exceptions; several hints may name the same entry.
Coverage targets are compared by the report parser instead.

Check assignments against the task if they would omit required behavior. Correct a mistaken
assignment or observation rather than treating a stage label as permission to ignore a requirement.
The cross-reference check validates the resulting IDs and assignments, not their engineering truth.

Prefer observations at the top boundary. If those cannot distinguish the required behavior,
explain the need for an internal observation in the hint and account for the implementation stage
still owning the module split. Expected values come from the task's reference, not the DUT.

Return STATUS: DONE with the output path, or STATUS: BLOCKED with what prevented completion.
