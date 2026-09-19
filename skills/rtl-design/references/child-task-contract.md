# Implement an RTL portion

The stage owner supplies a cohesive task, shared interfaces and input paths. Read the relevant
requirements, original intent, design choices, top-level boundary and clocks, plus
[coding-rules.md](coding-rules.md). Resolve interface discrepancies against these sources and the
assigned integration obligations. Write under `{workdir}/src/`; the stage owner coordinates
integration and further delegation.

Choose the file layout and compile order. Return `STATUS: DONE` with a JSON object containing
`files`, `incdirs` and `annotations`, or `STATUS: BLOCKED <cause>` if the work is incomplete.

- `files`: stage-relative source paths in compilation order. Headers reached through includes
  need no separate compilation entry. The entire `src/` tree is delivered.
- `incdirs`: stage-relative include search paths; omit or leave empty when none are needed.
- `annotations`: the `sgdc` and `sdc` categories in
  [constraint-annotations.schema.json](constraint-annotations.schema.json), for the structures
  this portion owns. Use actual RTL names and include the clock, reset and timing facts needed
  downstream. Coordinate annotations for shared integration logic with the stage owner.

The owner combines these reports into `rtl-files.json` and `constraint-annotations.json`.
