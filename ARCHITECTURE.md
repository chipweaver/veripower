# VeriPower Architecture

> How VeriPower organizes agent-driven chip design, and why it's built this way.

---

## 1. Overview

VeriPower is a chip front-end design and verification system. It takes an LLM
coding agent through eight stages, from a natural-language spec all the way to
power analysis, on commercial EDA tools (SpyGlass, Design Compiler, PrimeTime,
VCS+UVM).

The whole system is built around one idea. A deterministic kernel owns every
fact about the design flow. It knows which verification conclusions still hold,
what got invalidated by a change, what should run next, and who's responsible
for fixing a failure. LLM agents and human engineers both sit outside this
kernel. They can propose work and propose judgments. The kernel records them
through schema-validated, append-only operations.

<p align="center">
  <img src="assets/architecture.png" alt="VeriPower architecture" width="460" />
</p>

The **Orchestrator** is the `design-flow` skill running in the main
conversation. It asks the kernel for one action, carries it out, then asks
again. It holds nothing between queries and makes no routing decisions on its
own.

The **Deterministic kernel** (`framework/scripts/`) records events, derives
status, computes the dependency graph, schedules work, and checks whether an
attribution is legal. Everything it does is pure computation over the event log
and what's on disk.

The **Filesystem** is the only persistence layer. An append-only event log
(`events.jsonl`) plus whatever artifacts each stage produces. No database, no
daemon, no HTTP.

Stage agents don't talk to the orchestrator or to each other. Each one gets a
structured handoff written to disk by the kernel, not a natural-language
summary of the orchestrator's context, and writes its results back to disk.

---

## 2. The Pipeline

Eight rules make up the flow. A ninth, simulation triage, is a diagnostic that
analyzes simulation failures without recording a verification conclusion of its
own.

| Rule | What it does |
|---|---|
| specification | Accounts for the delivered intent in a source-grounded requirements ledger with explicit judgment responsibilities, then derives design decisions, interfaces and timing constraints |
| simulation-plan | Maps every specified behavior to a testpoint, produces the verification plan and TB scaffold |
| rtl-design | Generates RTL from the specification |
| lint-cdc | SpyGlass lint and CDC checks |
| synthesis | Design Compiler synthesis |
| timing-analysis | PrimeTime timing analysis |
| simulation | Builds and runs UVM testbench against the RTL |
| power-analysis | PrimeTime power analysis |
| simulation-triage | Root-cause analysis for simulation failures |

### Dependency graph

The graph comes from each rule's declared inputs in `rules.py`. An input names
a path under some stage's directory, and that stage is its producer — stage
roots are disjoint, so the producer is exact and nothing declares its outputs
twice. The graph stays aligned with those input declarations.

<p align="center">
  <img src="assets/pipeline-dag.png" alt="Pipeline dependency graph" width="660" />
</p>

*\*Specification's outputs (constraints, PPA targets, interface declarations)
are also consumed directly by lint-cdc, synthesis, simulation, and
power-analysis. Simulation-plan's outputs (verification plan, power scenario identifiers) are
consumed by power-analysis. These edges are omitted from the diagram for
clarity.*

Concurrency falls out naturally. Rules with no artifact edge between them can
run at the same time. Lint-cdc and simulation, for instance, share nothing and
regularly run in parallel. You can inspect the live graph yourself:

```bash
python3 -c "import sys; sys.path.insert(0,'framework/scripts'); import rules
for r in rules.FORWARD_PRIORITY: print(r, sorted(rules.input_producers(r)))"
```

---

## 3. State and Proofs

### The event log

A module's entire state lives in one append-only file, `events.jsonl`. There's
no status snapshot. Whether a stage is done, stale, failed, or still running
gets computed from the log against disk every time you ask. The kernel is the
only writer, and every record is schema-validated before it lands.

The orchestrator carries nothing between turns. If a context window gets
compacted or the process crashes, the next `decide` call just re-derives the
right action from disk.

### Proofs

When a rule completes, the kernel records a **proof**. That's a verdict (pass
or fail) bound to content fingerprints of every input consumed and every output
produced.

Validity is not stored anywhere. It's recomputed as a query. A proof holds
right now only if the verdict was pass, every recorded fingerprint for inputs
and outputs still matches what's on disk.
Only the latest collected outcome of that stage can supply the proof. An incomplete
collection leaves no current conclusion until it is resolved.

Say you edit one line of RTL. Next time anything checks the log, lint-cdc's,
synthesis's, and simulation's input fingerprints won't match anymore. Three
proofs go invalid at once. Nobody marks anything stale. Staleness is just the
absence of a matching fingerprint. Meanwhile specification and simulation-plan
are fine, because their inputs don't include RTL.

You can also query impact before making a change. Ask the kernel which
currently-valid proofs would break if a given file changed, so that when you
skip a stage, the decision rests on a graph computation, not a guess.

---

## 4. Failure and Repair

### A direct attribution

Synthesis reports a timing violation. It read Design Compiler's QoR report,
decided the critical path is too long in the RTL, and names rtl-design as the
rule that must fix it.

The kernel checks whether that's legal. Is rtl-design inside synthesis's
transitive dependency closure? It is (rtl-design produces RTL, synthesis
consumes it), so the attribution stands.

Next round, the kernel dispatches rtl-design with the failed synthesis run as
context. The RTL agent reads the timing report and shortens the critical path.
Now the RTL outputs have different fingerprints, so lint-cdc, synthesis, and
simulation all lose their proofs. The kernel re-verifies them in dependency
order. Everything passes. Done.

### A failure that needs investigation

Simulation fails, but it can't tell whether the bug is in the RTL, the
specification, or the testbench reference model. It doesn't name anyone.

The kernel sees an unattributed simulation failure. Simulation's rule points to
`simulation-triage` as its diagnostic, so the kernel dispatches triage. The
triage agent goes into the failed run's directory (UVM logs, FSDB waveforms,
coverage data), reads the spec and reference model, and if the evidence isn't
conclusive, builds a controlled experiment in its own workspace to nail down
the cause.

Triage finds that a clock-domain relationship was declared wrong in the spec.
The kernel confirms specification is inside simulation's dependency closure,
records the diagnosis, and routes the failure there.

Specification fixes the declaration. Downstream constraints change with it. The
kernel figures out which proofs are now invalid and re-verifies the affected
chain.

### How attribution works

The failing stage names who needs to act. The kernel's only job is to check
that the name is legal: the failed stage itself or a transitive input producer. There's no fixed table of labels. A closed set could only
cover failure modes someone thought of ahead of time, and where a symptom shows
up is not necessarily where its cause lives.

Unresolved or unrelated attributions require a decision from the available evidence under the
task's actual authorization. A stage can repair itself. Escalation includes candidates and evidence.

If multiple failures point to the same rule, they get bundled into one
dispatch. Lint-cdc and synthesis both blaming rtl-design won't make it run
twice.

---

## 5. The Trust Boundary

### Verification independence

Design and verification both start from the specification, then they split.
The design path produces RTL. The verification path produces the test
environment, and everything on that path (plan, scaffold, sequences, reference
model) derives from the specification. Simulation compiles the RTL and may
inspect it to diagnose failures. Expected behavior comes from the task's
independent references, so implementation behavior does not become its own oracle.

Every specified behavior gets mapped to a testpoint through structured artifact
handoffs between simulation-plan and simulation. After each simulation round,
an independent check-adequacy review checks
what the tests actually exercised against what the specification asked for.
This catches both missing checks and checks that test the wrong thing.

### Acceptance record

When the task calls for recorded acceptance, `signoff` checks that all stage conclusions are
current and published files are covered by their stage outcomes, then records the decision
maker, authorization and basis. Reserved decisions wait for the user; delegated decisions follow
the existing authorization. Ordinary completion does not require a separate signoff.

The record binds the stage evidence accepted at that event. Changed evidence invalidates it;
new stage conclusions need new acceptance. Signoff does not replace technical verification.
Concrete issues are checked by the responsible stage through the existing failure and repair flow.

---

## 6. Verification Scope

**Proof coverage follows declared inputs.** A rule can read other files, but
changes to those files are outside its recorded dependencies. What a stage
delivers is bounded — an input names a tree, and the tree
versions as a merkle over everything under it, so nothing inside one escapes by
being named unexpectedly — and the signoff gate refuses a stage whose canonical
directory holds a file its own outcome does not record.

**Versioning of the intent stops at the container's edge.** The intent tree is
one directory, `intent/`, holding `brainstorm.md` and whatever the engineer
delivered with it; every proof records one merkle over all of it, so editing the
document, editing an authority, or delivering the first one invalidates all eight
proofs and sends the flow back to `specification`. What that does not cover is
anything the document points at from outside: a path above the container is
neither handed to a stage nor versioned, and a symlink inside it is recorded by
its target path, not its target's content, so a shared spec that moves under the
link moves invisibly. Such a reference becomes a ledger row like any other
sentence, and whoever the row names has to establish it by reading it where it
lives.

**Signoff closes the declared verification obligations.** These are the
eight proofs the rule registry lists, each held to the
requirements-ledger rows that name it as judge. The ledger organizes source-grounded obligations and material context; a second reader checks
that nothing required is lost or invented. Shared wording can cover multiple obligations, and
repeated statements can share an entry when their meaning and judgment agree. Rows judged
`outside` retain explicit external responsibility and are not established by pipeline signoff.

---

## Key Terms

| Term | Meaning |
|---|---|
| **proof** | A verification conclusion tied to exact input and output versions. Validity gets recomputed every time it's queried. |
| **rule** | One unit of work the kernel schedules, with declared inputs, outputs and proof. The dependency graph falls out of these declarations. |
| **projection** | Per-rule status (valid, stale, failed, blocked, in-flight, or missing) computed from the event log and disk on demand. Never stored. |
