# RTL tool considerations

Use the task's reset polarity and kind from `top-io.json`, and assess implementation choices
against the required behavior and budgets. Report unmeasured trade-offs for the relevant analysis;
changes to acceptance follow the user's actual authorization.

The supplied tool flow has these constraints:

- DC can ignore procedural `initial` assignments and remove ROM contents that RTL simulation
  retained. Verify that the chosen ROM representation survives synthesis.
- The supplied SGDC `sync_cell -name` annotations name modules. Match annotations to the actual
  synchronizer structure; inline structures need appropriate SpyGlass constraints.
- Downstream compilation uses `rtl-files.json`. Include search paths belong in `incdirs`.
