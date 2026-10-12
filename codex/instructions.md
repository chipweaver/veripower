VeriPower on Codex

Use these native operations when running VeriPower:

- Load the bare skill X by reading @ROOT@/skills/X/SKILL.md in the current agent.
  Its directory is `<skill>`. Run the kernel as
  `python3 @ROOT@/framework/scripts/kernel.py ...`.
- Launch an independent background executor with `spawn_agent`, `message` set to the
  self-contained prompt and `fork_turns="none"`. The child loads its skill from the
  installed absolute SKILL.md path.
- Wait for children with `wait_agent` and collect their completion messages. For a stage
  executor, continue with `decide --wake RULE:RUN` once the executor has exited.
- For background shell jobs, use `exec_command` and wait for process exit with
  `write_stdin` before finishing the stage.
