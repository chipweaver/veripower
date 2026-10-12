VeriPower on Claude Code

- Load the bare skill X through Skill with `skill: "veripower:X"`.
  The kernel is `python3 @ROOT@/framework/scripts/kernel.py`.
- Launch a background executor through Agent with `subagent_type: "general-purpose"`,
  a description and the self-contained prompt, using the host's background execution mode.
- Collect executor results from native completion notifications.
  Yield when waiting for background completion; resume with `decide --wake RULE:RUN`.
- Execute shell work through Bash and collect background process results before stage closure.
