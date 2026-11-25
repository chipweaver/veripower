import path from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const SKILLS_DIR = path.join(ROOT, "skills")

const DISPATCH = /kernel\.py["']?\s+dispatch\b/
const KERNEL_CALL = /kernel\.py["']?\s+\w+/
const LOOP_REMINDER = (rule, run) =>
  `veripower loop: after the executor for \`${rule}\` run ${run} has started, ` +
  "call `kernel.py decide` to schedule other ready work."

const TOOL_MAPPING = `VeriPower on OpenCode 1:
Load the bare skill X with \`skill\` using { name: X }.
Launch an independent background executor with \`task\` using
{ subagent_type: "general", background: true, description: "short task label", prompt: P }.
Completion is delivered to the parent automatically. Yield while waiting; once the executor
has exited, continue with \`decide --wake RULE:RUN\`.
Execute commands through \`bash\` and wait for every process you start to exit before closing a stage.
VeriPower is installed at ${ROOT}. The kernel is \`${ROOT}/framework/scripts/kernel.py\`.`

// Read the native session's history so a restored session needs no adapter state.
function loopReminder(messages) {
  let reminder = null
  for (const message of messages) {
    for (const part of message.parts) {
      const state = part.state
      if (part.type !== "tool" || part.tool !== "bash") continue
      if (state?.status !== "completed" && state?.status !== "error") continue
      const command = state.input?.command
      if (typeof command !== "string" || !KERNEL_CALL.test(command)) continue
      reminder = null
      if (state.status !== "completed" || !DISPATCH.test(command)) continue
      try {
        const envelope = JSON.parse(state.output)
        if (envelope?.execution === "task") reminder = LOOP_REMINDER(envelope.rule, envelope.run)
      } catch {
        // Help text and failed CLI output are not dispatch envelopes.
      }
    }
  }
  return reminder
}

async function server({ client }) {
  return {
    config: async config => {
      config.skills ??= {}
      config.skills.paths = [...new Set([...(config.skills.paths ?? []), SKILLS_DIR])]
    },
    "experimental.chat.system.transform": async ({ sessionID }, output) => {
      output.system.push(TOOL_MAPPING)
      if (!sessionID) return
      const { data: messages } = await client.session.messages({
        path: { id: sessionID },
        throwOnError: true,
      })
      const reminder = loopReminder(messages)
      if (reminder) output.system.push(reminder)
    },
  }
}

export default { id: "veripower", server }
