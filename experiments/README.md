# Hardware experiments

These manual experiments exercise installed EDA tools and existing implementations.
They are independent of the maintained regression suite in `tests/`.
Set the site-specific tool and library environment before running them; store outputs
outside the repository. Measurements are evidence for the behavior exercised, not
universal acceptance criteria.

```bash
python3 experiments/runtime_fixes.py --workdir /path/visible/to/eda/runtime-fixes
python3 experiments/power/run.py --case fsa --synthesis /path/to/Design/synthesis \
  --reference /path/to/fa_core_ref.c --out /path/to/new-run
```

The first command checks coverage scope and numeric timing with VCS/URG, DC and
PrimeTime. The power driver uses existing FSA or gateGPT implementations; select
`--case microgpt` for the latter. Check clocks and matching SDF against the chosen
implementation. These workloads do not establish representative or peak power.
