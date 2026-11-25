import path from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const SKILLS_DIR = path.join(ROOT, "skills")

const LOOP_REMINDER = "VeriPower orchestration: if you are coordinating a module's stages, " +
  "call `kernel.py decide` after launching background work to schedule other ready work."

const TOOL_MAPPING = `VeriPower on OpenCode 1:
Load the bare skill X with \`skill\` using { name: X }.
Launch an independent background executor with \`task\` using
{ subagent_type: "general", background: true, description: "short task label", prompt: P }.
Completion is delivered to the parent automatically. Yield while waiting; once the executor
has exited, continue with \`decide --wake RULE:RUN\`.
Execute commands through \`bash\` and wait for every process you start to exit before closing a stage.
VeriPower is installed at ${ROOT}. The kernel is \`${ROOT}/framework/scripts/kernel.py\`.`

async function server() {
  return {
    config: async config => {
      config.skills ??= {}
      config.skills.paths = [...new Set([...(config.skills.paths ?? []), SKILLS_DIR])]
    },
    "experimental.chat.system.transform": async (_input, output) => {
      output.system.push(TOOL_MAPPING)
    },
    "tool.execute.after": async ({ tool }, output) => {
      if (tool === "task" && output?.metadata?.background === true) {
        output.output += "\n\n" + LOOP_REMINDER
      }
    },
  }
}

export default { id: "veripower", server }
