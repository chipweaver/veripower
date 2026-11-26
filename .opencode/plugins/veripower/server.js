import path from "path"
import { fileURLToPath } from "url"
import { existsSync, readFileSync, readdirSync } from "node:fs"
import { parse } from "yaml"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, "../../..")
const SKILLS_DIR = path.join(ROOT, "skills")

const LOOP_REMINDER = "VeriPower: if you just launched a stage executor, " +
  "call `kernel.py decide` now to schedule other ready work."

const LOCATION = `VeriPower is installed at ${ROOT}. The kernel is \`${ROOT}/framework/scripts/kernel.py\`.`
const TOOL_MAPPING = `VeriPower on OpenCode:
Load the bare skill X with \`skill\` using { id: "veripower:X" }.
Launch a background executor with \`subagent\` using
{ agent: "general", description: "short task label", prompt: P }.
Completion is delivered to the parent automatically. Execute commands through \`shell\`.
${LOCATION}`

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
  })
  await ctx.tool.hook("execute.after", event => {
    if (event.tool !== "subagent" || event.status !== "completed") return
    const content = event.result.content
    event.result.content = [
      ...(typeof content === "string" ? [{ type: "text", text: content }] : content),
      { type: "text", text: LOOP_REMINDER },
    ]
  })
}

export default { id: "veripower", setup }
