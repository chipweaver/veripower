import path from "path"
import { fileURLToPath } from "url"
import { existsSync, readFileSync, readdirSync } from "node:fs"
import { parse } from "yaml"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, "../../..")
const SKILLS_DIR = path.join(ROOT, "skills")

// Keep dispatch context until the next kernel action.
const DISPATCH = /kernel\.py["']?\s+dispatch\b/
const KERNEL_CALL = /kernel\.py["']?\s+\w+/
const LOOP_REMINDER = (rule, run) =>
  `veripower loop: after the executor for \`${rule}\` run ${run} has started, ` +
  "call `kernel.py decide` to schedule other ready work."

const LOCATION = `VeriPower is installed at ${ROOT}. The kernel is \`${ROOT}/framework/scripts/kernel.py\`.`
const TOOL_MAPPING = `VeriPower on OpenCode:
Load the bare skill X with \`skill\` using { id: "veripower:X" }.
Launch a background executor with \`subagent\` using
{ agent: "general", background: true, description: "short task label", prompt: P }.
Completion is delivered to the parent automatically. Execute commands through \`shell\`.
${LOCATION}`

// Reconstruct from native history so reminders survive session restoration and
// stay scoped to the executor whose command actually dispatched the run.
function loopReminder(messages) {
  const calls = new Map()
  let last = null
  for (const message of messages) {
    for (const part of message.content) {
      if (part.type === "tool-call" && part.name === "shell") {
        calls.set(part.id, part.input?.command)
      }
      if (part.type !== "tool-result" || part.name !== "shell") continue
      const command = calls.get(part.id)
      if (!command || !KERNEL_CALL.test(command)) continue
      last = null
      if (!DISPATCH.test(command)) continue
      if (part.result.type !== "text") continue
      const output = part.result.value
      try {
        const envelope = JSON.parse(output)
        if (envelope?.execution === "task") last = LOOP_REMINDER(envelope.rule, envelope.run)
      } catch {
        // Help text and failed CLI output are not dispatch envelopes.
      }
    }
  }
  return last
}

// Native OpenCode Promise plugin.
async function setup(ctx) {
  const skills = readdirSync(SKILLS_DIR, { withFileTypes: true })
    .filter(entry => entry.isDirectory() && existsSync(path.join(SKILLS_DIR, entry.name, "SKILL.md")))
    .map(entry => {
      const skillPath = path.join(SKILLS_DIR, entry.name, "SKILL.md")
      const text = readFileSync(skillPath, "utf8")
      const frontmatter = text.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)
      const metadata = parse(frontmatter[1])
      return {
        id: `veripower:${metadata.name}`,
        name: metadata.name,
        description: metadata.description,
        path: skillPath,
        content: text.slice(frontmatter[0].length),
      }
    })
  await ctx.skill.transform(editor => {
    for (const skill of skills) editor.add(skill)
  })
  await ctx.session.hook("context", event => {
    event.system.push({ type: "text", text: TOOL_MAPPING })
    const reminder = loopReminder(event.messages)
    if (reminder) event.system.push({ type: "text", text: reminder })
  })
}

export default { id: "veripower", setup }
