# VeriPower User Manual

For front-end design and verification engineers. Walks through the full flow from environment setup to signoff, in the order you'll actually do things. Intervention points are marked inline. Two cheat sheets at the end.

---

## §0 In one sentence

VeriPower takes a finalized module requirement all the way to front-end signoff. Spec, verification plan, RTL, lint/CDC, synthesis, timing, simulation, power. Nine stages, dispatched and reworked automatically by an Orchestrator. You step in at four types of checkpoints to control quality. **You're still the responsible engineer.** It doesn't make decisions for you, but it's a capable assistant. It also doesn't import your existing RTL or testbench. Right now it regenerates them from the spec.

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

The first flag enables the background subagents stage dispatch runs on. Without the second,
opencode (as of 1.18.x) caps every completion at 32,000 tokens regardless of the model's
declared limit, and a subagent authoring a whole module's RTL dies silently mid-thought.

DeepSeek Harness — install into the profile you run:

```bash
dsh plugin --profile web add "veripower@git+https://github.com/chipweaver/veripower.git"
dsh web
```

It installs as a profile layer and finds its own `skills/`, so there is nothing to
configure. Use `web`, not the one-shot `headless` profile — a dispatched stage outlives the
turn that started it, and `headless` exits when the turn ends.

Codex — install the native plugin (tested with CLI 0.153.4 on Linux):

```bash
codex plugin marketplace add chipweaver/veripower
codex plugin add veripower@chipweaver --json
```

Run `python3 <installedPath>/codex/setup.py` using the install response's path, then
start `codex --profile veripower`. Review all two VeriPower hooks in `/hooks` and
start a new session. The dedicated profile keeps judgment approvals with the human;
background stages use native subagents and the parent waits before continuing.
See [Codex setup](../codex/README.md) for upgrade steps and the tested scope.

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

It checks each tool and variable, does a live checkout of each license, and reports which stages this machine can run. Read-only, it won't change your environment. When a variable is missing, it prints the `export` line for you to paste.

### 1.2 Input

The entire pipeline reads one directory: `{module}/intent/`. The document goes in it as `brainstorm.md`, and everything the document leans on goes in with it — organize the inside however you like. Two ways to get there.

**Option A: you already have a spec.** Save it as `{module}/intent/brainstorm.md`, in whatever shape it is, and put anything it refers to in that directory too: a reference model, a register map, a standard's text. Whatever your document names as authoritative is read there by the stage that needs it. Two things to know. A file left outside `intent/` is not part of the intent — no stage is handed it, and no stage notices when it changes; if your document points at one, the stage that needs it will say so at your first gate. And a symlink is recorded by where it points, not by what is there, so a shared spec that changes under the link changes invisibly — copy it in instead. No need to run brainstorm: `specification` transcribes every requirement the document states into `requirements.json`, one row each in your words, and assumes nothing about how the document is organized.

**Option B: generate from scratch.** In a **separate session**:

> Run the brainstorm skill for {module}

It asks one question at a time, each with the answer it would give and why, so you are picking
rather than composing. It is done when your scope, functions, top-level IO, clocks and resets
and their crossings, architecture partition, timing scenarios, PPA targets, and what the
downstream stages need are each either settled or deliberately left open. What you already
brought, it does not ask again.

When it finishes, it **hands you the path only**, not the content. Read the file on disk and **confirm it looks right to start the pipeline**.

Whichever route you take, what the document says is what the pipeline will hold the design to, and nothing more: a bound you did not write is not judged, a requirement you wrote is either judged by a stage, judged by you at the ledger gate, or shown to you as something the pipeline cannot judge. Clocks and top-level interfaces the document leaves out will surface at the ledger gate as rows the specification stage could not realize.

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
                                      signoff (you, §1.6)
```

The work tree splits into `Design/` and `Verification/`. Each stage below covers three things: **what it does**, **artifacts**, and **your action**.

The third column in artifact tables tells you whether to read it. **Must read** means the pipeline will put the path in front of you at a gate. **Optional** means you'd look at it during review. Unmarked files are consumed by scripts or downstream tools.

**You don't need to watch for when to act.** Where there's a **gate**, the pipeline stops and asks (specification has two, simulation-plan has one). When it needs you to attribute a failure, it stops. At signoff it blocks on each endorsement individually.

The items marked "read xx" or "glance at xx" are review actions. The pipeline won't stop for them. `semantic-review` and `refmodel` will get caught at signoff if you haven't endorsed them yet. Only lint-cdc's `waiver.tcl` has no prompt anywhere. If you want to check it, go look on your own.

---

#### specification

**What it does:** turns the brainstorm into frozen design documents and boundary files. Three steps. Decomposition (partition into sub-modules), sub-design per child (parallel ×N), semantic review per child (parallel ×N).

**Artifacts** (`{module}/Design/specification/`)

| File | What it is | Read it? |
|---|---|---|
| `design.md` | Module overview §1.1–1.6, §1.7 points to manifest | **Must read** |
| `<child>.md × N` | Sub-design for each child module | **Must read** |
| `requirements.json` | Everything your intent document requires, one row each in your own words, with the stage that will judge it. The gate shows you verbatim the rows nobody could place (`unassignable`), the rows judged outside this pipeline, the rows left to you, and the numeric bounds the tools will compare | **Must read those four groups** |
| `manifest.json` | The top RTL module's name, and nothing else | Optional |
| `spec-review/findings/requirements.md` / `findings/<child>.md` / `decisions.md` | The ledger checked against your document, each child design checked against the ledger, and your rulings | **Must read** |
| `check-hints.json` | How simulation will observe each requirement row it judges | Optional |
| `clocks.json` / `top-io.json` | Boundary info: clocks and their arrival budgets, top-level ports | `design.md` §1.3 is the human-readable version |
| `constraints/<TOP>.sdc` / `.sgdc` | Constraint pair generated from clocks + top-io | Generated, not a decision |

**Your action: one gate, then a handoff**

- **Ledger and boundary gate** (after the requirements review): resolve every `unassignable` row (define how it is measured, assign a judge, or declare it not a requirement), read the rows judged outside the pipeline and the ones left to you, check the numeric bounds, confirm the partition or give feedback to repartition. These are answers the pipeline cannot compute, so it waits for them.
- **The delivery handoff** (after the child reviews): you get the paths and nothing is asked of you. Read whether `design.md` and each `<child>.md` realize the ledger rows they cite, and say what you want changed. Endorsing the reviews is `kernel.py pin` (#6 below) — until then the module cannot be signed off, so an unresolved blocking finding stops the module rather than the round.

> Decisions made earlier in the pipeline have the biggest impact. The spec stage is the source for everything that follows. Take the time.

---

#### simulation-plan

**What it does:** derives the testpoint matrix, TB scaffold, stimulus sequences, and power scenarios from the spec.

**Artifacts** (`{module}/Verification/simulation-plan/`)

| File | What it is | Read it? |
|---|---|---|
| `verification-plan.md` | §3 testpoint matrix + §4 power scenarios. This is what you read when the round is handed over | **Must read** |
| `plan-review/findings.md` / `decisions.md` | Review findings and your rulings | **Must read** |
| `tb-scaffold.json` | TB scaffold: testpoint and agent definitions | Optional, plan §3 is the human-readable version |
| `power-scenarios.json` | Power scenarios, consumed by power-analysis | Optional, plan §4 is the human-readable version |
| `sequences.json` | Stimulus sequence definitions | No need |

**Your action: a handoff.** You get the `verification-plan.md` and `plan-review/findings.md` paths, and nothing is asked of you. Say what you want changed and it revises incrementally and comes back; if you tell it to accept a finding the review flagged as blocking, your exact words get recorded in `plan-review/decisions.md`. Endorsing the review is `kernel.py pin` (#6 below), and nothing downstream re-checks testpoint-vs-spec — so an unaddressed gap stops the module at signoff.

> Once the testpoint matrix is locked, the TB, regression, and coverage convergence all follow from it. This gate is worth the time.

---

#### rtl-design

**What it does:** writes RTL from the sub-designs and declares timing exceptions and generated clocks into `constraint-annotations.json`. Downstream lint-cdc and synthesis constraints both come from here.

**Artifacts** (`{module}/Design/rtl-design/`)

| File | What it is | Read it? |
|---|---|---|
| `semantic-review/*.md` | Review of RTL against design intent | **Must read**, required for signoff endorsement |
| `*.v` | RTL source | Optional |
| `constraint-annotations.json` | Timing exceptions and generated clocks implied by this RTL, using real module names. Lint-cdc and synthesis constraints come from here | Optional |
| `rtl-files.json` | Per-child `files[]` + `incdirs[]`, every downstream filelist is generated from it | No need |

**Your action: read `semantic-review/*.md`.** It's one of the four artifacts you need to endorse before signoff (§1.6). The pipeline won't stop here to wait for you, but reading it early can save a rework round.

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
| `scripts/constraints.sgdc` | Assembled SGDC: spec seed + RTL annotations + `local.sgdc` | Editing it won't help, next run reassembles from scratch |

**Your action: glance at `scripts/waiver.tcl`.** Violations it deems acceptable are written as `waive` entries with reasons. **Clean lint does not mean zero violations.** Pass/fail itself is determined by the SpyGlass ruleset. No input needed from you.

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

**Your action: none.** To review, read `reports/qor.rpt` and `result.json`'s `requirements[]`. The judgment comes from dc_shell's QoR report, against the rows you approved at the ledger gate. It won't invent timing exceptions. SDC exceptions can only be transcribed from the `constraint-annotations.json` declared by rtl-design. If a path truly can't meet timing, it reworks back upstream rather than adding a false path to hide it.

---

#### timing-analysis

**What it does:** reads the synthesis netlist + SDC and runs static timing analysis in the background.

**Artifacts** (`{module}/Design/timing-analysis/`)

| File | What it is | Read it? |
|---|---|---|
| `timing-report.txt` | Setup/hold slack report. The judgment reads this | Optional |

**Your action: none.** To review, read `timing-report.txt`. The judgment comes from pt_shell's report.

---

#### simulation

**What it does:** turns the verification plan into a UVM testbench, runs regression, converges coverage. When a test case fails and the stage can't tell who should fix it, it automatically dispatches `simulation-triage` to dig through waveforms (`fsdbreport`), failure logs, and case lists, attributing each failure. The scheduler routes rework to whichever stage the attribution names.

**Artifacts** (`{module}/Verification/simulation/`)

| File | What it is | Read it? |
|---|---|---|
| `tb/uvm/refmodel/**` | Reference model that judges correctness | **Must read**, required for signoff endorsement |
| `case-results-summary.md` | Per-case result summary | Optional |
| `structural-coverage.json` | Structural coverage: line / cond / branch / toggle / fsm | Optional |
| `regression-log.txt` + `logs/` | Regression log plus per-case logs | Optional, check when you want to know why a specific case failed |
| `tb/uvm/**` (rest) | UVM testbench proper | Optional |
| `check-review.md` | Per-testpoint check adequacy review | Internal to this stage, not for human consumption |
| `env.sh` / `filelist.f` / `rtl_filelist.f` / `tests/testlist.json` / `case-results.json` | Environment, compile file lists, case list, machine-readable results | No need |

**Your action: read the reference model `tb/uvm/refmodel/*` carefully.** It's the ruler that judges right from wrong. Of the four artifacts you'll endorse, this one deserves the most scrutiny (§1.6). If the ruler is wrong, every green in the regression is a lie. The pipeline won't stop here, and rework doesn't need your direction.

---

#### power-analysis

**What it does:** the two chains converge here. Runs gate-level simulation in the background using the synthesis netlist + SDF and the simulation TB environment, produces SAIF, then runs PT-PX for average power, judging every `requirements.json` row assigned to power-analysis.

**Artifacts** (`{module}/Verification/power-analysis/`, `<id>` = power scenario)

| File | What it is | Read it? |
|---|---|---|
| `reports_ptpx/<id>/power_flat.rpt` | Total power for this scenario. PPA judgment reads this | Optional |
| `reports_ptpx/<id>/switching_activity.rpt` | How much switching came from SAIF vs. tool defaults | Optional. If SAIF didn't annotate, the power number is meaningless |
| `reports_ptpx/<id>/power_hier.rpt` | Hierarchical power breakdown | Optional, look at it when you need to reduce power |
| `saif/<id>.saif` | One SAIF per scenario. Scenarios with equivalent stimuli simulate once and share results | No need |
| `reports_ptpx/<id>/ptpx.log` | PT-PX log for this scenario | Only when something goes wrong |

**Your action: none.** To review, read `reports_ptpx/<id>/power_flat.rpt`. The judgment comes from pt_shell's report. After this stage, the pipeline has nothing left to run. Signoff is a separate act you initiate (§1.6).

---

**Check progress anytime.** Ask "where is {module} right now?" Each stage is in one of six states:

| State | Meaning |
|---|---|
| `missing` | Never been run |
| `in-flight` | Currently running |
| `valid` | Completed, result currently trustworthy |
| `stale` | Completed, but something upstream changed. Result is now invalid, will be rebuilt next round |
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

The pipeline will stop and show you the reason **verbatim**, along with candidate attributions if applicable. The only way to resume is **a human attribution**, stating which stage should fix it and why.

A common case is the spec stage saying it can't fix itself, which usually means **the requirements need to change**. Rerun brainstorm in revision mode, update `intent/brainstorm.md`, and the spec stage's result automatically goes invalid. Resume the flow from there.

More error messages in [Appendix B](#appendix-b-error-reference).

### 1.6 Signoff

**Pipeline completion is not signoff.** Completion means every stage has a result and the result is currently valid. Signoff is you, as the responsible engineer, doing a final end-to-end review of those results and putting your name on them. It only starts when you ask:

> Run signoff for {module}

**Why this step exists.** Of the eight stages, four have their pass/fail determined by tools. SpyGlass's ruleset, dc_shell's QoR report, pt_shell's timing and power reports. The tool output itself is authoritative. The other four have their pass/fail determined by something an LLM wrote, and that needs your final review:

| Stage | What judges pass/fail |
|---|---|
| specification | `spec-review/findings/*.md`, LLM-authored spec review |
| simulation-plan | `plan-review/*.md`, LLM-authored plan review |
| rtl-design | `semantic-review/*.md`, LLM-authored RTL review |
| simulation | `tb/uvm/refmodel/*`, LLM-authored reference model, the ruler for every test case |

LLM-authored artifacts can't vouch for themselves. **So signoff requires you to read and endorse each of those four.**

**Three things you do**

1. **Ask for signoff** (the sentence above).
2. **Endorse each of the four.** It tells you which one is missing, e.g. "rtl-design's review hasn't been endorsed." You read the file, confirm it, and give a one-line reason for why you endorse it. The reason and your identity are recorded in the audit log.
3. **Review what you're signing, then approve.** Once all four are endorsed and every stage result is still valid, it lays out the signoff basis stage by stage. What judged it, who endorsed the judgment, what the content looked like when you endorsed it, which tool was used, which files this stage consumed. You review all of that and approve. Only then does signoff land, recording who signed and why.

Steps 2 and 3, and "withdraw an endorsement," are all **ask-gated actions**. Each one prompts for confirmation.

> **Endorsement is bound to content, not the filename.** It records what the file looks like at that moment. If the file changes, the endorsement lapses automatically. You have to re-read and re-endorse. You're signing the content itself.

**Signoff reverts on its own.** After signoff, if you change any upstream design file or withdraw any endorsement, the module immediately drops back to unsigned. Nobody needs to revoke anything. Signoff is only as strong as the results underneath it.

One more thing you probably won't hit: if a file gets **added to a stage's inputs outside the pipeline**, the gate won't clear. Either remove the file or let the stage rerun to formally record it.

### 1.7 Artifacts and exit paths

**Directory tree**

```
{module}/
├── intent/                        # The pipeline's sole input: brainstorm.md + what it leans on (yours, pipeline reads only)
├── events.jsonl                   # Audit log, the only persistent state file
├── Design/
│   ├── specification/             # design.md / <child>.md / *.json / constraints/ / spec-review/
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

opencode: remove the plugin entry from `opencode.json`, then remove the skill link the
plugin created at `~/.claude/skills/veripower` (nothing removes it on its own):

```bash
rm ~/.claude/skills/veripower
```

**Can I use the artifacts without this tool?**

Yes. RTL is standard `.v` plus a filelist (`rtl-files.json`). The TB is standard UVM with `filelist.f` + `env.sh`, and `vcs` can compile it directly. Constraints are standard SDC/SGDC. Synthesis, timing, and power artifacts are just the tools' own netlists and reports. **Only `events.jsonl` belongs to this tool.** Deleting it doesn't affect whether anything else can run. What you lose is the audit trail, not the design.

---

## §2 Glossary

The body of this manual uses familiar terms where possible. Below are the words you'll see in the plugin internals and log files.

| Plugin term | What it means |
|---|---|
| stage / rule | A pipeline stage. One stage = one rule |
| proof | Evidence that a stage's result is currently trustworthy. Records which files it read, which it produced (content fingerprints), and what judged it |
| oracle / judge | **The judgment artifact**, the thing that determines pass/fail. Either a tool report or an LLM-authored review |
| grade (`proposed` / `tool` / `human`) | How trustworthy the judgment is. `proposed` = LLM-authored, needs your endorsement before signoff (becomes `human` after endorsement) |
| pin | Your **endorsement** of an LLM-authored judgment. Records a fingerprint of the content at that moment |
| reopen | Withdraw an endorsement |
| stale | Something upstream changed, this result is no longer valid. Not a flag. Recomputed on every query |
| event log / `events.jsonl` | Audit log, the only persistent state file |
| dispatch / reap | Send a stage off to run / collect its result |
| decide | The scheduler. Ask it "what next?" and it returns exactly one action |
| DISPATCH / REAP / YIELD / DONE / ESCALATE | Send off / collect / something is still running, wait / all green / **needs your input** |
| workdir / run | A stage's working directory for a particular round / the round number |
| input closure | All upstream artifacts a result transitively depends on |
| fix_owner | Which stage should fix this failure |
| signoff | The act of putting your name on a set of results |

---

## Appendix A: Intervention point reference

| # | When | Stage | What you decide | Can you skip it? | Details |
|---|---|---|---|---|---|
| 1 | Requirements dialogue | brainstorm (before pipeline) | Requirements and architecture, including PPA targets | No | §1.2 |
| 2 | Ledger and boundary gate | specification, after the requirements review | Resolve `unassignable` rows, read the rows outside the pipeline and yours, check the bounds, confirm the partition | No, and it's the **last chance to change the partition** | §1.4 |
| 3 | Delivery handoff | specification, after the child reviews | Nothing — read the reviews and say what you want changed; you endorse them at #6 | Yes | §1.4 |
| 4 | Delivery handoff | simulation-plan | Nothing — same; you endorse the plan review at #6 | Yes | §1.4 |
| 5 | ESCALATE | any stage | Attribute the failure to a stage and say why | No | §1.5 |
| 6 | Endorse judgments | four LLM-authored artifacts | Read, confirm, give a reason | Required before signoff | §1.6 |
| 7 | Signoff | after all stages | Review the signoff basis and approve | Yes. Without it the module stays in delivery state | §1.6 |

1–4 are required for normal pipeline progression. 5 only appears when something goes wrong. 6–7 only appear when you ask for signoff. **Nothing else waits for you.** Between gates 2, 3, 4 and after gate 4, it runs on its own.

## Appendix B: Error reference

**Scheduling and rework**

| Message | What it means | What to do |
|---|---|---|
| `no module directory at <path>` | Module directory doesn't exist, probably a wrong path | Retry with the absolute path to the module directory |
| `<stage>: envelope named no fix_owner` | Stage failed but didn't say who should fix it | You attribute it: name which upstream stage should fix it and why (§1.5) |
| `<stage>: fix_owner is itself, in-stage remedy exhausted` | Stage tried everything it can | Look upstream. When spec reports this, it usually means **the requirements need to change**. Rerun brainstorm |
| `<stage>: fix_owner '<x>' is outside its input closure` | The failing stage doesn't actually consume anything from the stage you named | Re-attribute. You can only name stages it actually reads from (including transitively) |
| `<stage>: diagnosis named no fix_owner` | Triage ran but didn't identify who should fix it | It lists the candidates for you. Pick one and explain why |
| `<stage>: the oracle that judged this failure was reopened` | You withdrew your endorsement of the judgment that found this failure | Let it rerun the stage |
| `intent tree incomplete: intent/brainstorm.md is not there…` | The pipeline has no intent document to start from | Put your document at `{module}/intent/brainstorm.md`, with anything it names as authoritative beside it |

**Signoff gate**

| Message | What it means | What to do |
|---|---|---|
| `signoff blocked: <stage> not valid` | That stage's result has gone stale | Let the flow continue running to rebuild it |
| `signoff blocked: <stage> oracle is proposed (pin it)` | You haven't endorsed that stage's LLM-authored judgment yet | Read it, confirm, and give a reason. See §1.6 |
| `signoff blocked: <stage> has unverified new input(s) <file>` | A file was added to that stage's inputs outside the pipeline | Remove the file, or let the stage rerun to formally record it |

**Environment and tools**

| Symptom | Cause | Fix |
|---|---|---|
| An EDA stage immediately reports an unset variable | `LIB_DB` / `LIB_V` / `UVM_HOME` not exported | First `echo $VAR` to confirm it's really unset (don't go searching the filesystem yet), then export and rerun |
| `compile_ultra` can't check out a license | No DC-Ultra license | The synthesis stage is entirely unavailable. There's no fallback to plain `compile` |
| Linker error when building `simv` | Host GCC incompatible with VCS pre-compiled objects | `export VCS_CC=<gcc>` / `export VCS_CPP=<g++>` (GCC 4.8 is a known-good combination on some VCS + newer distro setups) |
| Coverage parsing fails | Your `urg` version has a different report layout than L-2016.06 | Switch to L-2016.06, or report the version difference to the plugin maintainers. It **won't** fake a "coverage met" |
| VCS launcher behaves strangely | `/bin/sh` is not bash | Debian/Ubuntu: `sudo dpkg-reconfigure dash` and select No |
| Environment check hangs on license probing | License server unreachable | Fix the network first, or point to a different license server |

---

## Further reading

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md): why it's built this way. The pipeline and how the dependency graph is derived, proof validity, how a failure gets attributed, the trust boundary, and what the system does not do.
- [`eda-env.md`](eda-env.md): full EDA tool, license, and environment requirements.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md): replacing a stage's implementation (e.g. Verilator for simulation, Yosys for synthesis).
