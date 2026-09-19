# VeriPower User Manual

For front-end design and verification engineers. Walks through the full flow from environment setup to signoff, in the order you'll actually do things. Intervention points are marked inline. Two cheat sheets at the end.

---

## §0 In one sentence

VeriPower takes a finalized module requirement all the way to front-end signoff. Spec, verification plan, RTL, lint/CDC, synthesis, timing, simulation, power. Eight stages, dispatched and reworked automatically by an Orchestrator. Your participation follows the decisions needed and the authorization you give.

---

## §1 Full Walkthrough

`{module}` refers to the module name throughout. The entire work tree lives in a directory with that name, and that's what you pass in commands. If you're not in its parent directory, give the path.

### 1.1 Before you start

**Install the plugin**

Claude Code:

```bash
claude plugin marketplace add chipweaver/veripower
claude plugin install veripower@chipweaver
```

Or clone the source and launch from the command line: `claude --plugin-dir /path/to/veripower`.

opencode — add the plugin to `~/.config/opencode/opencode.json`, or to a project-level
`opencode.json`:

```json
{ "plugin": ["veripower@git+https://github.com/chipweaver/veripower.git"] }
```

then start it with:

```bash
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true \
OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=131072 opencode
```

The first flag enables background subagents. opencode 1.18.30 has a default
32,000-token completion ceiling. For models that support longer output, set the
second flag to the model's declared output limit; `131072` is an example.

DeepSeek Harness — install into the profile you run:

```bash
dsh plugin --profile web add "veripower@git+https://github.com/chipweaver/veripower.git"
dsh web
```

It installs as a profile layer and finds its own `skills/`, so there is nothing to
configure. Use `web`, not the one-shot `headless` profile — a dispatched stage outlives the
turn that started it, and `headless` exits when the turn ends.

Codex — install the native plugin (tested with CLI 0.154.0 on Linux):

```bash
codex plugin marketplace add chipweaver/veripower
codex plugin add veripower@chipweaver --json
```

Launch with `codex --enable hooks --enable multi_agent`, review the two VeriPower hooks in
`/hooks`, and start a new session. The plugin uses native subagents and preserves host permissions.
See [Codex setup](../codex/README.md) for integration and verification scope.

**Python**

Supports **3.10 / 3.11 / 3.12**.

```bash
python3 --version
```

Install dependencies:

```bash
pip install "jsonschema>=4.18" referencing PyYAML
```

Or from the source directory:

```bash
pip install -r requirements.txt
```

**EDA tools and licenses**

See [`eda-env.md`](eda-env.md) for the full list of tools and variables. This includes `dc_shell` / `pt_shell` / `vcs` / `spyglass`, `fsdbreport` / `fsdb2vcd`, `make` / `urg`, license variables, `LIB_DB` / `LIB_V` / `UVM_HOME`, and `/bin/sh` pointing to `bash`.

If you're only running `specification` / `simulation-plan` / `rtl-design`, skip this. No EDA tools needed.

**`env-precheck` environment check**

Once the environment is ready, in a **separate session**:

> Run the env-precheck skill

It checks each tool and variable, does a live checkout of each license, and reports which stages this machine can run. It reports the findings without changing your environment. When a variable is missing, it prints the `export` line for you to paste.

### 1.2 Input

The entire pipeline reads one directory: `{module}/intent/`. The document goes in it as `brainstorm.md`, and everything the document leans on goes in with it — organize the inside however you like. Two ways to get there.

**Option A: you already have a spec.** Save it as `{module}/intent/brainstorm.md`, in whatever shape it is, and put anything it refers to in that directory too: a reference model, a register map, a standard's text. Whatever your document names as authoritative is read there by the stage that needs it. Two things to know. Files outside `intent/` are not automatically delivered or versioned as intent. Identify any necessary missing basis; tools and artifacts assigned to later work are prepared by their responsible stage. And a symlink is recorded by where it points, not by what is there, so a shared spec that changes under the link changes invisibly — copy it in instead. No need to run brainstorm: `specification` accounts for the intent in `requirements.json`, preserving source wording, conditions and responsibility. Repeated statements can share an obligation without forcing the document into a fixed format.

**Option B: generate from scratch.** In a **separate session**:

> Run the brainstorm skill for {module}

It asks one question at a time, each with the answer it would give and why, so you are picking
rather than composing. It is done when your scope, functions, top-level IO, clocks and resets
and their crossings, architecture partition, timing scenarios, PPA targets, and what the
downstream stages need are each either settled or deliberately left open. What you already
brought, it does not ask again.

When it finishes, it **hands you the path only**, not the content. Read the file on disk and **confirm it looks right to start the pipeline**.

Whichever route you take, what the document says is what the pipeline will hold the design to, and nothing more: a bound you did not write is not judged, each obligation is assigned to a stage, a decision under the actual authorization, or an explicit external responsibility. Necessary missing definitions remain visible; implementation choices and assets to be created are assigned to their responsible work.

> **Not currently supported:** importing existing RTL or testbench as engineering artifacts. They can serve as conversational input to brainstorm, but RTL and TB are still regenerated by the pipeline.

### 1.3 Launch

In a **separate session**:

> Run the design-flow skill for {module}

The Orchestrator takes over. Each round it asks the scheduler "what next?", and the scheduler returns **exactly one** action for it to carry out. From this point on, you only step in at intervention points.

### 1.4 Stage by stage

```
[brainstorm]  (before the pipeline, separate session)
     ↓
intent/brainstorm.md
     ↓
[specification] → [simulation-plan] → [rtl-design]
                                            │
                          ┌─────────────────┴──────────────────┐
                          ↓                                    ↓
                     [lint-cdc]                          [simulation]
                          ↓                                    │
                     [synthesis]                               │
                          ↓                                    │
                  [timing-analysis]                            │
                          └─────────────────┬──────────────────┘
                                            ↓
                                    [power-analysis]
                                            ↓
                                      signoff (when in scope, §1.6)
```

The work tree splits into `Design/` and `Verification/`. Each stage below covers three things: **what it does**, **artifacts**, and **your action**.

The third column in artifact tables tells you whether to read it. **Must read** marks material needed for the corresponding decision; who makes it follows the task's authorization. **Optional** means you'd look at it during review. Unmarked files are consumed by scripts or downstream tools.

**The pipeline follows the actual authorization.** It presents unresolved decisions when human input is needed, continues within an existing delegation, and records acceptance when it is in scope.

The items marked "read xx" or "glance at xx" are review actions. The pipeline won't stop for them. Review lint-cdc's `waiver.tcl` directly; it has no separate approval prompt.

---

#### specification

**What it does:** establishes requirements, design choices and interface/clock boundaries from the original intent, derives constraints and obtains independent review. Organize authoring and delegation around the work; RTL design owns the module split.

**Artifacts** (`{module}/Design/specification/`)

| File | What it is | Read it? |
|---|---|---|
| `design.md` | Architecture, boundary, joint obligations and timing scenarios | **Must read** |
| `requirements.json` | Source-grounded obligations and judgment responsibilities. Independent conclusions remain distinguishable; repeated statements can share an entry. The ledger view shows unresolved items (`unassignable`), external responsibilities, decisions and numerical bounds | **Must read those four groups** |
| `manifest.json` | The top RTL module's name, and nothing else | Optional |
| `spec-review/findings/` / `decisions.md` | Independent review and material decisions with their basis and authorization | **Must read** |
| `check-hints.json` | How simulation will observe each requirement row it judges | Optional |
| `clocks.json` / `top-io.json` | Boundary info: clocks and their arrival budgets, top-level ports | `design.md` §1.3 is the human-readable version |
| `constraints/<TOP>.sdc` / `.sgdc` | Constraint pair generated from clocks + top-io | Generated, not a decision |

**Your participation:** review unresolved requirements, numerical bounds and boundary choices. Decisions needing your input arrive with their basis; work within an existing delegation continues. Review `design.md` and the findings at delivery. An unresolved violation prevents this stage from passing; signoff is not a substitute for resolving it.

---

#### simulation-plan

**What it does:** derives the testpoint matrix, TB scaffold, stimulus sequences, and power scenarios from the spec.

**Artifacts** (`{module}/Verification/simulation-plan/`)

| File | What it is | Read it? |
|---|---|---|
| `verification-plan.md` | §3 testpoint matrix + §4 power scenarios. This is what you read when the round is handed over | **Must read** |
| `plan-review/findings.md` / `decisions.md` | Review findings and recorded decisions | **Must read** |
| `tb-scaffold.json` | TB scaffold: testpoint and agent definitions | Optional, plan §3 is the human-readable version |
| `power-scenarios.json` | Power scenarios, consumed by power-analysis | Optional, plan §4 is the human-readable version |
| `sequences.json` | Stimulus sequence definitions | No need |

**Your participation:** review `verification-plan.md` and `plan-review/findings.md`. The stage resolves findings against their evidence; an unresolved blocking finding prevents the stage from passing. Decisions follow the actual authorization and are recorded with their basis in `plan-review/decisions.md`.

> The testpoint matrix guides TB authoring, regression and coverage convergence.

---

#### rtl-design

**What it does:** implements the required behavior and boundary, reviews the RTL, and declares timing exceptions and generated clocks in `constraint-annotations.json`. Downstream lint-cdc and synthesis constraints both come from here.

**Artifacts** (`{module}/Design/rtl-design/`)

| File | What it is | Read it? |
|---|---|---|
| `semantic-review/*.md` | Review of RTL against design intent | Useful for reviewing this delivery |
| `*.v` | RTL source | Optional |
| `constraint-annotations.json` | Timing exceptions and generated clocks implied by this RTL, using real module names. Lint-cdc and synthesis constraints come from here | Optional |
| `rtl-files.json` | Per-child `files[]` + `incdirs[]`, every downstream filelist is generated from it | No need |

**Your participation:** `semantic-review/*.md` explains the RTL review findings and their resolution. Use it to assess the delivery or discuss a concrete concern.

After this stage, the pipeline forks into the implementation chain and the simulation chain, running in parallel.

---

#### lint-cdc

**What it does:** runs SpyGlass lint and CDC checks in the background.

**Artifacts** (`{module}/Design/lint-cdc/`)

| File | What it is | Read it? |
|---|---|---|
| `scripts/waiver.tcl` | Violations it judged acceptable, each with a reason | **Must read** |
| `lint-report.txt` / `cdc-report.txt` | Raw SpyGlass reports | Optional |
| `lint-violations.json` / `cdc-violations.json` | Structured violation lists | Optional |
| `scripts/local.sgdc` | SGDC annotations added by this stage for port/clock associations the seed can't know | Optional |
| `scripts/constraints.sgdc` | Assembled SGDC: spec seed + RTL annotations + `local.sgdc` | Reassembled each run; edit `scripts/local.sgdc` for stage-local annotations |

**Your action: glance at `scripts/waiver.tcl`.** Violations it deems acceptable are written as `waive` entries with reasons. **Review waived violations as well as the reported counts.** Pass/fail itself is determined by the SpyGlass ruleset. No input needed from you.

---

#### synthesis

**What it does:** runs `compile_ultra` synthesis in the background, judges every `requirements.json` row assigned to synthesis.

**Artifacts** (`{module}/Design/synthesis/`)

| File | What it is | Read it? |
|---|---|---|
| `reports/qor.rpt` | QoR report. PPA judgment reads this | Optional |
| `constraints.local.sdc` | Timing exceptions transcribed from `constraint-annotations.json` | Optional |
| `out/<TOP>_syn.v` / `_syn.sdc` / `_syn.sdf` | Post-synthesis netlist, exported SDC, delay annotation | Consumed by downstream timing/power |
| `constraints.sdc` | Assembled constraints: spec SDC + `constraints.local.sdc` | Assembly product |

**Your action: none.** To review, read `reports/qor.rpt` and `result.json`'s `requirements[]`. The judgment comes from dc_shell's QoR report, against the requirements recorded in the ledger. SDC exceptions come from the `constraint-annotations.json` declared by rtl-design. A path that cannot meet timing is routed upstream for repair.

---

#### timing-analysis

**What it does:** reads the synthesis netlist + SDC and runs static timing analysis in the background.

**Artifacts** (`{module}/Design/timing-analysis/`)

| File | What it is | Read it? |
|---|---|---|
| `timing-report.txt` | Setup/hold slack report. The judgment reads this | Optional |

**Your action: none.** To review, read `timing-report.txt`. The judgment comes from pt_shell's report.

Synthesis and STA choose work from the actual change. Applicable measurements can be judged against current requirements without recalculation. The `run` entrypoint uses `config.tcl` and temporary working data. Successful calculations move checked products into the workdir; failed calculations retain logs and temporary output for diagnosis until retry. Source notes travel with the result without becoming downstream hardware inputs. Setup, calculation and closure are independent; a new stage run does not require a new synthesis.

---

#### simulation

**What it does:** implements the testbench, independently reviews its checks, runs regression and investigates coverage gaps. The stage owner assesses findings against evidence and repairs local defects. RTL may inform diagnosis; expected behavior still comes from independent sources. When a test case fails and the stage can't tell who should fix it, it automatically dispatches `simulation-triage` to dig through waveforms (`fsdbreport`), failure logs, and case lists, attributing each failure. The scheduler routes rework to whichever stage the attribution names.

**Artifacts** (`{module}/Verification/simulation/`)

| File | What it is | Read it? |
|---|---|---|
| `tb/uvm/refmodel/**` | Reference model that judges correctness | Useful for reviewing this delivery |
| `case-results-summary.md` | Per-case result summary | Optional |
| `structural-coverage.json` | Structural coverage: line / cond / branch / toggle / fsm | Optional |
| `regression-log.txt` + `logs/` | Regression log plus per-case logs | Optional, check when you want to know why a specific case failed |
| `tb/uvm/**` (rest) | UVM testbench proper | Optional |
| `check-review.md` | Per-testpoint check adequacy review | Used by the stage to direct check repairs |
| `env.sh` / `filelist.f` / `rtl_filelist.f` / `tests/testlist.json` / `case-results.json` | Environment, compile file lists, case list, machine-readable results | No need |

**Your participation:** `tb/uvm/refmodel/*` supplies expected behavior for regression checks. Inspect it when assessing what the tests establish or investigating a discrepancy.

---

#### power-analysis

**What it does:** the two chains converge here. Reads the planned measurement purpose, reuses suitable verification components, and authors a complete power experiment. Checks actual conditions, captures SAIF and calculates interval-average power with PT-PX, then assesses requirements using both experimental validity and tool results.

**Artifacts** (`{module}/Verification/power-analysis/`, `<id>` = power scenario)

| File | What it is | Read it? |
|---|---|---|
| `analysis.md` / `experiment/` | Measurement interpretation and runnable experiment sources | When reviewing |
| `reports_ptpx/<id>/power_flat.rpt` | Total power for this scenario. PPA judgment reads this | Optional |
| `reports_ptpx/<id>/switching_activity.rpt` | How much switching came from SAIF vs. tool defaults | Optional, check that the measured scenario activity was annotated |
| `reports_ptpx/<id>/power_hier.rpt` | Hierarchical power breakdown | Optional, look at it when you need to reduce power |
| `saif/<id>.saif` | Activity used for each scenario | No need |
| `reports_ptpx/<id>/ptpx.log` | PT-PX log for this scenario | Only when something goes wrong |

For review, start with `analysis.md` for measured conditions, checks and conclusions, then inspect the referenced reports. Decisions about acceptance follow the actual human or delegated authorization. After this stage, the pipeline has nothing left to run. Signoff records acceptance when it is in scope (§1.6).

---

**Check progress anytime.** Ask "where is {module} right now?" Each stage is in one of six states:

| State | Meaning |
|---|---|
| `missing` | Never been run |
| `in-flight` | Currently running |
| `valid` | Recorded pass; its input and output fingerprints still match |
| `stale` | Recorded pass, but an input or output has changed; the affected work needs reassessment |
| `failed` | Completed, judgment says it didn't pass |
| `blocked` | Can't proceed (missing environment, crashed) |

### 1.5 Special situations

**I edited RTL by hand. Will it get overwritten? What's the source of truth?**

Disk is the source of truth. The moment you save, **the stage that produced that file and every downstream stage that reads it all go invalid at once**. Every result records content fingerprints of its inputs and outputs. If the fingerprints don't match, the result no longer holds.

**Your edit will not be rolled back.** But because the stage that produced the file also went invalid, the next scheduling round will rebuild it. The agent works **on top of your edit**. Your version is its starting point, not something it discards.

**Ctrl-C / SSH dropped / machine rebooted**

Just say "continue the design flow for {module}" in a new session. There's no separate recovery procedure. The scheduler queries the event log and the files on disk to pick up where things left off. As long as the directory is there, any new session can resume.

The one thing that needs you: the interrupted round will still show as "in-flight." Once you confirm the executor is dead, tell it to close out that run. The next round reroutes from there.

**It's stuck / keeps editing the same thing**

The flow presents the unresolved cause and candidate repair owners. Resolve the attribution from evidence under the actual task authorization; `diagnose` records that decision.

A stage may repair its own work. Revise intent only when the evidence and authorization support a requirement change.

More error messages in [Appendix B](#appendix-b-error-reference).

### 1.6 Signoff

`signoff` records acceptance of the current verification evidence, when the task calls for it.
The flow checks the stage conclusions and delivered artifacts, then follows the actual authorization:
reserved decisions are presented with their basis and wait for you; delegated decisions proceed in
scope. `provenance` records the decision maker and authorization; `reason` records the acceptance
basis. Host execution permissions remain separate.

Signoff binds the accepted evidence. Changed evidence invalidates it; restoring the same evidence
can restore validity, while new stage conclusions need new acceptance. Signoff does not replace
technical verification or turn a failed check into a pass.

Files in a published stage directory must be covered by that stage's recorded artifacts. For an unrecorded file, determine whether it belongs in the delivery, then remove it or close the stage with the relevant evidence.

### 1.7 Artifacts and exit paths

**Directory tree**

```
{module}/
├── intent/                        # The pipeline's sole input: brainstorm.md + what it leans on (yours, pipeline reads only)
├── events.jsonl                   # Audit log, the only persistent state file
├── Design/
│   ├── specification/             # design.md / *.json / constraints/ / spec-review/
│   ├── rtl-design/                # *.v / rtl-files.json / semantic-review/
│   ├── lint-cdc/                  # reports + violations JSON + scripts/
│   ├── synthesis/                 # out/*_syn.{v,sdc,sdf} / reports/qor.rpt
│   └── timing-analysis/           # timing-report.txt
└── Verification/
    ├── simulation-plan/           # verification-plan.md / *.json / plan-review/
    ├── simulation/                # tb/uvm/ / filelist.f / env.sh / case-results-summary.md
    ├── simulation-triage/         # failure analysis (only exists if triggered)
    └── power-analysis/            # reports_ptpx/*/power_hier.rpt
```

Each stage also produces a `result.json` (that round's status envelope).

**What to put in git** (suggested, not enforced)

Track: `intent/`, `events.jsonl` (audit trail), `Design/specification/`, `Design/rtl-design/*.v` + `rtl-files.json`, `Verification/simulation-plan/`, `Verification/simulation/tb/`, and the final reports from each stage.

Ignore: tool intermediates and run directories. `*.svf`, `*.pvl`, `command.log`, `pt_shell_command.log`, `simv*`, `csrc/`, synthesis and PT work directories, waveforms (FSDB files tend to be large).

**Uninstall**

Claude Code:

```bash
claude plugin uninstall veripower@chipweaver
```

opencode: remove the plugin entry from `opencode.json` and start a new session.

**Can I use the artifacts without this tool?**

Yes. RTL is standard `.v` plus a filelist (`rtl-files.json`). The TB is standard UVM with `filelist.f` + `env.sh`, and `vcs` can compile it directly. Constraints are standard SDC/SGDC. Synthesis, timing, and power artifacts are just the tools' own netlists and reports. `events.jsonl` preserves the VeriPower audit trail; the design artifacts also run with the EDA tools directly.

---

## §2 Glossary

The body of this manual uses familiar terms where possible. Below are the words you'll see in the plugin internals and log files.

| Plugin term | What it means |
|---|---|
| stage / rule | A pipeline stage. One stage = one rule |
| proof | A stage's pass/fail conclusion, bound to recorded input and output fingerprints |
| stale | An input or output changed, so the recorded pass is no longer current. Recomputed on every query |
| event log / `events.jsonl` | Audit log, the only persistent state file |
| dispatch / reap | Send a stage off to run / collect its result |
| decide | The scheduler. Ask it "what next?" and it returns exactly one action |
| DISPATCH / REAP / YIELD / DONE / ESCALATE | Send off / collect / something is still running, wait / all green / **needs an attribution or decision** |
| workdir / run | A stage's working directory for a particular round / the round number |
| input closure | All upstream artifacts a result transitively depends on |
| fix_owner | Which stage should fix this failure |
| signoff | A recorded acceptance of specific stage evidence under the task's authorization |

---

## Appendix A: Intervention point reference

| # | When | Stage | What you decide | Can you skip it? | Details |
|---|---|---|---|---|---|
| 1 | Requirements dialogue | brainstorm (before pipeline) | Requirements and architecture, including PPA targets | No | §1.2 |
| 2 | Requirements and boundary decisions | specification | Resolve open requirements and confirm bounds/boundary with their evidence | Follow the actual authorization; do not infer technical proof from approval | §1.4 |
| 3 | Delivery handoff | specification, after independent review | Review the design and findings; the stage resolves violations before passing | Yes | §1.4 |
| 4 | Delivery handoff | simulation-plan | Review the plan and findings as needed | Yes | §1.4 |
| 5 | ESCALATE | any stage | Attribute the failure to a stage and say why | No | §1.5 |
| 6 | Signoff | after all stages | Accept the evidence under the actual authorization | Only needed when recorded acceptance is in scope | §1.6 |

These are decision and review points, not mandatory permission prompts. Human participation follows the actual authorization; signoff records acceptance when the task calls for it.

## Appendix B: Error reference

**Scheduling and rework**

| Message | What it means | What to do |
|---|---|---|
| `no module directory at <path>` | Module directory doesn't exist, probably a wrong path | Retry with the absolute path to the module directory |
| `<stage>: envelope named no fix_owner` | Stage failed but didn't say who should fix it | Identify the failed stage itself or an input producer as the repair owner, with the reason (§1.5) |
| `<stage>: fix_owner ... is neither itself nor an input producer` | Repair owner is unrelated to the failed stage | Name the failed stage or a stage whose artifacts it consumes |
| `<stage>: diagnosis named no fix_owner` | Triage ran but didn't identify who should fix it | It lists the candidates for you. Pick one and explain why |
| `intent tree incomplete: intent/brainstorm.md is not there…` | The pipeline has no intent document to start from | Put your document at `{module}/intent/brainstorm.md`, with anything it names as authoritative beside it |

**Signoff gate**

| Message | What it means | What to do |
|---|---|---|
| `signoff blocked: <stage> not valid` | That stage has no current passing conclusion | Let the flow resolve the missing work, failure or changed evidence |
| `signoff blocked: <stage> has unrecorded file(s) <file>` | A published stage directory contains files not covered by its latest outcome | Assess whether the files belong in the delivery, then remove them or close the stage with the relevant evidence |

**Environment and tools**

| Symptom | Cause | Fix |
|---|---|---|
| An EDA stage immediately reports an unset variable | `LIB_DB` / `LIB_V` / `UVM_HOME` not exported | First `echo $VAR` to confirm it's really unset (don't go searching the filesystem yet), then export and rerun |
| `compile_ultra` can't check out a license | No DC-Ultra license | Provide a DC-Ultra entitlement for `compile_ultra` |
| Linker error when building `simv` | Host GCC incompatible with VCS pre-compiled objects | `export VCS_CC=<gcc>` / `export VCS_CPP=<g++>` (GCC 4.8 is a known-good combination on some VCS + newer distro setups) |
| Coverage parsing fails | Your `urg` version has a different report layout than L-2016.06 | Switch to L-2016.06, or report the version difference to the plugin maintainers. |
| VCS launcher behaves strangely | `/bin/sh` is not bash | Debian/Ubuntu: `sudo dpkg-reconfigure dash` and select No |
| Environment check hangs on license probing | License server unreachable | Fix the network first, or point to a different license server |

---

## Further reading

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md): why it's built this way. The pipeline and how the dependency graph is derived, proof validity, how a failure gets attributed, the trust boundary, and the scope of verification.
- [`eda-env.md`](eda-env.md): full EDA tool, license, and environment requirements.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md): replacing a stage's implementation (e.g. Verilator for simulation, Yosys for synthesis).
