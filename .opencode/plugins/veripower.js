import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, "../..")
const SKILLS_DIR = path.join(ROOT, "skills")

// Keep dispatch context until the next kernel action.
const DISPATCH = /kernel\.py["']?\s+dispatch\b/
const KERNEL_CALL = /kernel\.py["']?\s+\w+/
const LOOP_REMINDER = (rule, run) =>
  `veripower loop: after the executor for \`${rule}\` run ${run} has started, ` +
  "call `kernel.py decide` to schedule other ready work."

// Applied to each session, including background subagents.
const TOOL_MAPPING = `<EXTREMELY_IMPORTANT>
You are running VeriPower (an IC design flow) on opencode. These tool translations apply:

1. \`Skill(X)\` -> call the \`skill\` tool with { name: X } and follow the returned content.
   Skills use bare names: \`veripower:lint-cdc\` becomes \`lint-cdc\`.
2. \`Task(run_in_background=True, prompt=P)\` -> call the \`task\` tool with
   { subagent_type: "general", background: true, prompt: P }. It returns immediately; you are
   notified when the subagent finishes.
3. VeriPower is installed at ${ROOT}. The kernel is \`${ROOT}/framework/scripts/kernel.py\`.
</EXTREMELY_IMPORTANT>`

// Task launch does not close this window; the next kernel action does.
function remindLoop(msgs) {
  let host = null
  let part = null
  for (const m of msgs) {
    for (const p of m.parts) {
      const st = p.state
      if (p.type !== "tool" || p.tool !== "bash" || st?.status !== "completed") continue
      if (KERNEL_CALL.test(String(st.input?.command ?? ""))) {
        host = m
        part = p
      }
    }
  }
  if (!host || !DISPATCH.test(String(part.state.input.command))) return
  let envelope
  try {
    envelope = JSON.parse(part.state.output)
  } catch {
    return
  }
  if (envelope?.execution !== "task") return
  host.parts.push({ ...part, type: "text", text: LOOP_REMINDER(envelope.rule, envelope.run) })
}

export default async () => {
  return {
    config: async (config) => {
      config.skills = config.skills || {}
      config.skills.paths = [...new Set([...(config.skills.paths || []), SKILLS_DIR])]
    },
    "experimental.chat.messages.transform": async (_input, output) => {
      const msgs = output.messages
      if (!msgs.length) return
      remindLoop(msgs)
      const firstUser = msgs.find((m) => m.info.role === "user")
      if (!firstUser || !firstUser.parts.length) return
      if (
        firstUser.parts.some(
          (p) => p.type === "text" && p.text.includes("EXTREMELY_IMPORTANT"),
        )
      ) {
        return
      }
      const ref = firstUser.parts[0]
      firstUser.parts.unshift({ ...ref, type: "text", text: TOOL_MAPPING })
    },
  }
}
