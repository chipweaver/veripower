# VeriPower Evaluation Harness (`eval/`)

Measures the **signoff-clean pass@1** of two arms on the same design — `full`
(the VeriPower pipeline) vs `B1-lean` (a plain Claude Code session on the bare
EDA tools) — plus their token/wallclock cost. The judge is external,
**arm-blind**, and **symmetric**: both arms' final RTL are scored by the SAME
fixed constraints and the SAME independent golden, so no arm passes by grading
itself or by writing lax constraints. Methodology and pre-registration live in
`docs/retrospective/2026-07-13-veripower-evaluation-plan.md` (§1.3 is the bar).

## Layout

| Dir | Role |
|-----|------|
| `b1-wrapper/` | Arm-neutral bare EDA tool layer (VCS/UVM, DC, PT, SpyGlass, urg), standard flags, no orchestration. Given to the B1 arm; reused verbatim by the judge. |
| `adjudicate/` | The arm-blind signoff-clean judge (quality). `adjudicate.py`. |
| `golden/<design>/` | Per-design independent golden: `reference.py` (held-out vectors), the fixed testbench, `golden_run.sh` (the runner). |
| `fixed/<design>/` | Per-design fixed §1.3 bar: `design.sdc`, `design.sgdc`. |
| `aggregate/` | Cost aggregator (tokens + wallclock). `aggregate.py`. |
| `runs/` | All outputs (verdicts, logs, per-run sandboxes) — gitignored except `.gitkeep`. |

## The two arms

- **`full`** — the VeriPower pipeline. Output is the module work tree
  `asic/<module>/` (its `events.jsonl`, `Design/rtl-design/<module>.v` +
  `filelist.txt`, `Design/specification/`, …). Its top RTL module is named after
  the module dir, e.g. **`fa_core_indep_0`** (the per-repeat name).
- **`B1-lean`** — a plain Claude Code session driving `b1-wrapper`. Output is a
  self-contained dir (`rtl/`, `filelist.txt`, `tb/`, `constraints/`, …). It
  names its top after the spec's pinned name, **`fa_core_indep`**.

⚠️ The two arms name their top module **differently** (per-repeat dir vs pinned
name). Everything else (ports, 64-bit beat bit-lanes) is the pinned interface.
Pass each arm's actual top via `--top` (below); the golden testbench binds the
DUT by that name (`+define+DUT_TOP`).

## Prerequisites

- EDA tools on `PATH`: `vcs`, `dc_shell`, `pt_shell`, `spyglass`. They are
  **containerized** — run everything under `$WORKSPACE_ROOT` (`/home/cgy/project`
  here); a workdir under `/tmp` fails to launch the tool container.
- Env: `LIB_DB`, `LIB_V`, `UVM_HOME`, `LM_LICENSE_FILE` (see `docs/eda-env.md`).
- `python3` only — the golden is pure stdlib (no torch/numpy).

## Quality: signoff-clean adjudication

`signoff_clean` = four criteria AND'd (§1.3), fail-loud (clean only on positive
evidence; any tool/parse failure → not clean and `adjudication_partial=true`):

1. **golden** — independent held-out golden passes (functional, black-box).
2. **lint** — SpyGlass lint clean (fixed SGDC, no waivers).
3. **cdc** — SpyGlass CDC clean (fixed SGDC).
4. **timing** — DC synth completes AND PT STA setup/hold WNS ≥ 0 (fixed SDC,
   `compile_ultra`).

One run = one (arm, design, seed):

```sh
python eval/adjudicate/adjudicate.py \
  --arm <full|B1-lean> --design flash_attn --seed <i> \
  --rtl-sourcelist <arm's RTL-only filelist> \
  --fixed eval/fixed/flash_attn \
  --top <DUT top module> \
  --golden-cmd "$PWD/eval/golden/flash_attn/golden_run.sh --rtl filelist.txt --top <DUT top module> --seeds <held-out seeds>" \
  --out eval/runs/adj-flash_attn [--append]
```

- `--rtl-sourcelist` — the arm's **RTL-only** filelist (synth RTL, no TB/UVM).
  Relative paths resolve against the filelist's own dir. (full arm:
  `asic/.../Design/rtl-design/filelist.txt`; B1: its `filelist.txt`.)
- `--top` **and** the golden-cmd `--top` must both be the arm's real top module
  name (full → `fa_core_indep_0`, B1 → `fa_core_indep`).
- `--golden-cmd` runs with cwd = the per-run sandbox, whose `filelist.txt`
  already holds absolute RTL paths — so `--rtl filelist.txt` is correct there.
- Held-out seeds are chosen by the operator and kept from both arms; they are
  NOT the arms' own dev seeds.

Worked example — both arms of one design:

```sh
FULL=asic-or-eval_test/.../asic/fa_core_indep_0/Design/rtl-design/filelist.txt
B1=asic-or-eval_test/.../claude/fa_core_indep_0/filelist.txt
GRUN="$PWD/eval/golden/flash_attn/golden_run.sh"

python eval/adjudicate/adjudicate.py --arm full --design flash_attn --seed 0 \
  --rtl-sourcelist "$FULL" --fixed eval/fixed/flash_attn --top fa_core_indep_0 \
  --golden-cmd "$GRUN --rtl filelist.txt --top fa_core_indep_0 --seeds 1,2,3,4,5" \
  --out eval/runs/adj-flash_attn

python eval/adjudicate/adjudicate.py --arm B1-lean --design flash_attn --seed 0 \
  --rtl-sourcelist "$B1" --fixed eval/fixed/flash_attn --top fa_core_indep \
  --golden-cmd "$GRUN --rtl filelist.txt --seeds 1,2,3,4,5" \
  --out eval/runs/adj-flash_attn --append
```

Each call writes/append a verdict row to `eval/runs/adj-flash_attn.{json,csv}`
keyed `(arm, design, seed, module)`. Smoke the wiring without tools using
`--dry-run`.

## The golden (`golden/<design>/`)

Independent oracle, held out from both arms. `reference.py` computes attention in
**exact fp32** (not the DUT's fp16/exp2 approximations, so the tolerance measures
only the DUT's own error) and emits held-out vectors; the fixed testbench scores
**top-level output only** (black-box — no internal probes) against per-tile
`MaxErr < 1e-2 && MAE < 1e-3`. One testbench binds any DUT honoring the pinned
interface; the DUT module name is the only knob (`+define+DUT_TOP`, via
`golden_run.sh --top`). `golden_run.sh` exit 0 == `GOLDEN: PASS` (the marker is
the sole positive evidence — VCS `$fatal` does not set a nonzero exit).

Regenerate vectors standalone: `python reference.py --seeds 1,2,3 --format tb`.
Unit tests (known-answer + invariants): `python -m pytest golden/flash_attn/test_reference.py`.

## The fixed bar (`fixed/<design>/`)

`design.sdc` (single clock, spec-nominal period; closure-only, no perf target)
and `design.sgdc` (single clock domain; input ports associated to that domain so
CDC setup is complete). Identical for both arms — never an arm's own SDC/SGDC.

## Cost aggregation

```sh
python eval/aggregate/aggregate.py --manifest <manifest.json> --out eval/runs/cost-flash_attn
```

Per run it computes `task_tokens` / `mainthread_tokens` / `total_tokens` and
wallclock. The `full` arm's cost comes from `asic/<module>/events.jsonl`
(`outcome.cost_tokens`, else a re-scan of the run's `.subagent_traces/`); the
main-thread and B1 costs come from the manifest-supplied session transcripts.
Rows are keyed the same as adjudicate's, so the two join into the final
Pareto table. See `aggregate.py --help` and its module docstring for the manifest
schema.

## Status

Validated end-to-end on **flash_attn** against real DUTs from both arms:
signoff-clean across all four criteria with the fixed bar + independent golden.
Adding another design = a new `golden/<design>/` + `fixed/<design>/` at the
same altitude.
