VeriPower on Codex

Apply these translations when running VeriPower:

- `Skill(veripower:X)`: read @ROOT@/skills/X/SKILL.md in the current agent.
  Its directory is `<skill>`. Run the kernel as
  `python3 @ROOT@/framework/scripts/kernel.py ...`; native approval rules cover
  `pin`, `reopen` and `signoff` at this path.
- `Task(run_in_background=True, prompt=P)`: use `spawn_agent` with `message=P`
  and `fork_context=false`. Render the child's Skill(...) line as a request to
  read its absolute SKILL.md path.
- When a skill ends a turn to await children, use `wait_agent` instead. Collect
  their results and close finished agents with `close_agent`. For a stage
  executor, continue with `decide --wake RULE:RUN` once the executor has exited.
- For background shell jobs, use `exec_command` and wait for process exit with
  `write_stdin` before finishing the stage.
