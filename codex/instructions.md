VeriPower on Codex

These translations apply only while executing a VeriPower skill or its dispatched
work. The installed plugin root is @ROOT@. Its kernel is
@ROOT@/framework/scripts/kernel.py. `<skill>` means the actual directory containing
the selected SKILL.md; pass that absolute directory to children that need it.

- `Skill(veripower:X)` means read @ROOT@/skills/X/SKILL.md and follow it in the
  current agent. Codex lists these skills under the `veripower:` namespace. There
  is no requirement to find a tool literally named Skill.
- `Task(run_in_background=True, prompt=P)` means spawn a native Codex subagent
  with P. Use a fresh context (`fork_context=false`, or `fork_turns="none"` on
  hosts using that parameter); the rendered contract and the child's skill are
  its inputs. Pass the child's absolute skill
  path in place of the template's Skill(...) instruction. Use the same mechanism
  for the Level-1 author/reviewer Tasks a main-thread stage explicitly requests.
  Respect the rendered stage contract's ban on further delegation.
- After launching a task executor, immediately call kernel.py decide again. Only
  the kernel selects the next action. Keep the returned agent id associated with
  its rule/run until the executor finishes.
- On YIELD with live executors, report progress in commentary and wait using
  Codex's agent-wait mechanism. Continue the kernel loop when an executor finishes.
  If the host reports that an executor died without result.json, pass its
  `--wake RULE:RUN` to decide so the kernel can reap that failed execution. A wait
  timeout is not executor death. Release finished agents with the host's close
  tool when available so completed threads do not consume the concurrency limit.
  Do not end the root turn merely to wait: this also works in codex exec, where
  ending the turn can close the process. The same waiting translation applies
  when a main-thread stage says to end its turn awaiting its Level-1 children.
  On DONE or ESCALATE, or when a human answer is required, return to the user.
- Long EDA commands use exec_command and its returned session id. Poll with
  write_stdin until the process exits; a yielded session is not a completed job.
  Stage agents stay alive until their EDA jobs finish and result.json is written.
- Human questions use the available Codex question tool or a plain question when
  that tool cannot accept an answer in this mode. Never infer consent from a
  timeout. Human oracle judgments still require the native approval prompt.
- Issue pin, reopen and signoff as one plain command with literal arguments:
  python3 @ROOT@/framework/scripts/kernel.py VERB ...
  Present the signoff basis first, as design-flow requires. The adapter normalizes
  that invocation to the exact argv protected by native prompt rules. Do not use
  shell variables, wrappers, redirections or compound commands for these verbs.
  Use the veripower profile with the human reviewer; don't replace approval with
  auto-review, permission bypass, or an allow-list entry. A rejected command is a
  rejection, not a reason to try another spelling or execute it through Python.

@SETUP@
