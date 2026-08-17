import fs from "fs"
import os from "os"
import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, "../..")
const SKILLS_DIR = path.join(ROOT, "skills")

// opencode discovers skills at ~/.claude/skills/** (a documented global path) and that
// discovery is the ONLY one that reaches a subagent: a plugin-injected config.skills.paths
// serves the main agent alone (measured). VeriPower's task stages run as subagents and load
// their stage skill by name, so the link is the mechanism, not a convenience.
const LINK = path.join(os.homedir(), ".claude", "skills", "veripower")

// Deliberately loose: `*kernel.py signoff*` misses `kernel.py  signoff` (two spaces) and lets
// an unreviewed signoff through. Over-matching costs one extra confirmation; missing costs a
// signature nobody gave.
const GATED_GLOBS = ["*kernel.py*pin*", "*kernel.py*reopen*", "*kernel.py*signoff*"]

// Reaches the main agent only — `messages.transform` reads the first user message of the
// session, and a subagent's session is not it. Everything here is therefore addressed to the
// orchestrator; a subagent gets what its rendered prompt and its own skill carry.
const TOOL_MAPPING = `<EXTREMELY_IMPORTANT>
You are running VeriPower (an IC design flow) on opencode. VeriPower's skills are written for a
Claude Code harness. These translations apply here:

1. \`Skill(X)\` -> call the \`skill\` tool with { name: X } and follow the returned content.
2. \`Task(run_in_background=True, prompt=P)\` -> call the \`task\` tool with
   { subagent_type: "general", background: true, prompt: P }. It returns immediately; you are
   notified when the subagent finishes.
3. VeriPower is installed at ${ROOT}. A skill's base directory is reached through a symlink, so
   resolving \`<skill>/../..\` yourself lands outside the install — address anything above a
   skill's own directory as \`${ROOT}/...\` instead (the kernel is
   \`${ROOT}/framework/scripts/kernel.py\`).
</EXTREMELY_IMPORTANT>`

// A throw here is swallowed by opencode (measured: exit 0, empty stderr, skills silently
// unregistered), so the link is attempted and never forced. An occupied path keeps whatever is
// already there — the visible consequence is that VeriPower's skills do not appear.
function linkSkills() {
  try {
    if (fs.realpathSync(LINK) === fs.realpathSync(SKILLS_DIR)) return
    console.error(
      `veripower: ${LINK} points elsewhere; VeriPower's skills will not be registered. ` +
        `Remove it and restart opencode.`,
    )
  } catch {
    fs.mkdirSync(path.dirname(LINK), { recursive: true })
    fs.symlinkSync(SKILLS_DIR, LINK, "dir")
  }
}

// Agent rules beat global ones and the last matching rule wins, so an agent carrying
// `"*": "allow"` opens the judgment verbs again unless the gate is restated after it.
function gate(permission) {
  permission.bash =
    typeof permission.bash === "string" ? { "*": permission.bash } : permission.bash || {}
  for (const g of GATED_GLOBS) {
    delete permission.bash[g]
    permission.bash[g] = "ask"
  }
}

export default async () => {
  linkSkills()
  return {
    config: async (config) => {
      config.permission = config.permission || {}
      gate(config.permission)
      config.permission.external_directory =
        config.permission.external_directory || {}
      config.permission.external_directory[`${ROOT}/**`] = "allow"
      for (const agent of Object.values(config.agent || {})) {
        if (typeof agent.permission === "object" && agent.permission !== null) {
          gate(agent.permission)
        }
      }
    },
    "experimental.chat.messages.transform": async (_input, output) => {
      if (!output.messages.length) return
      const firstUser = output.messages.find((m) => m.info.role === "user")
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
