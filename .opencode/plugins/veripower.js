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

// The permission prompt renders the command text and nothing else (measured: no message
// field, and the `tui` export receives the server-side PluginInput — no toast channel in
// 1.18.x), and the text it shows IS `output.args.command` as mutated here, because
// permission is evaluated after `tool.execute.before` (measured). The sentence therefore
// rides a no-op prefix: read, approved, and executed are the same string. Double quotes
// because the sentence carries apostrophes and no `"`/`$`/backtick.
const SENTENCE =
  "veripower trust boundary: judgment verb — it converts the agent's own " +
  "self-assessment into signoff-grade trust, so it is yours to make, not the " +
  "agent's. Approve only if you intended this call"

// Mirrors the globs' substring semantics within one shell segment (`;`/`|`/`&` split): every
// command the globs raise a prompt on, this catches — so the sentence rides every prompt, and
// the unarmed block below covers every gated shape. `K=…kernel.py; python3 $K signoff` (verb
// and path in different segments) matches nothing here, exactly as it matches no glob.
const JUDGMENT_VERB = /kernel\.py[^;|&]*(pin|reopen|signoff)/

// The post-dispatch loop rule, re-presented until the orchestrator's next kernel action
// closes the window. SKILL.md states it once near position 0; deep in a session the
// orchestrator stops running it and starts predicting what `decide` would have said,
// silently costing parallel runs (loop-reminder-parity.md). Same matcher as the Claude
// Code twin (hooks/loop_after_task_dispatch.py); the wording is the measured artifact,
// kept byte-identical to its REMINDER.
const DISPATCH = /kernel\.py\s+dispatch\b/
// Any `kernel.py <verb>` shell call — the window-closer. Kept as a shape, not a verb
// list: a list here would be one more thing that can disagree with the CLI. A grep
// whose text mentions kernel.py closes the window too; that costs one window of the
// reminder, never a wrong firing.
const KERNEL_CALL = /kernel\.py\s+\w+/
const LOOP_REMINDER = (rule, run) =>
  `veripower loop: \`${rule}\` run ${run} is in flight and this turn is not over. ` +
  "Your next call is `kernel.py decide` — now, before reaping it and before " +
  "reporting. Make it even when you expect YIELD."

// False until the config hook has written the gate into the effective config. A judgment
// verb arriving while false means the gate is not installed (config threw, or its write was
// lost): fail CLOSED — a throw here aborts the bash call (measured), so nothing lands ungated.
let armed = false

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
4. A subagent never sees this block. In the stage template's \`Skill({skill})\` line, render
   the child's call yourself: the \`skill\` tool with { name: <skill> }, stripping the
   \`veripower:\` namespace the dispatch return carries — skills register under bare names.
</EXTREMELY_IMPORTANT>`

// A throw in the factory is swallowed by opencode (measured: exit 0, empty stderr), so the
// link is attempted and never forced. A live foreign target keeps whatever is already there
// (hint printed below); a DANGLING link — the normal state after a cache/ref invalidation —
// is removed, because leaving it makes symlinkSync throw EEXIST and kill the whole plugin,
// gate included. A real directory never reaches the catch: realpath resolves it.
function linkSkills() {
  try {
    if (fs.realpathSync(LINK) === fs.realpathSync(SKILLS_DIR)) return
    console.error(
      `veripower: ${LINK} points elsewhere; VeriPower's skills will not be registered. ` +
        `Remove it and restart opencode.`,
    )
  } catch {
    fs.mkdirSync(path.dirname(LINK), { recursive: true })
    fs.rmSync(LINK, { force: true })
    fs.symlinkSync(SKILLS_DIR, LINK, "dir")
  }
}

// The coupling that makes a broken gate visible: skills ride the symlink, so if the gate
// cannot be installed the symlink goes away and VeriPower's skills stop listing. Only ever
// removes OUR link (realpath match), never an occupied path.
function unlinkSkills() {
  try {
    if (fs.realpathSync(LINK) === fs.realpathSync(SKILLS_DIR)) fs.rmSync(LINK, { force: true })
  } catch {
    /* not ours or absent: leave it */
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

// Appends the loop reminder while the LAST kernel-verb call in the outbound messages is
// still the `task` dispatch itself. Superseding on the next kernel action — not the next
// tool call — is the fix this port needed: the subagent-launch `task` part used to end
// the reminder, so the model's end-turn decision, the moment the reminder exists for,
// happened with it absent (measured: the one in-episode miss). Non-kernel actions (the
// task launch, reads) leave the window open. The guards on the dispatch itself mirror
// the Claude Code hook; on opencode a non-zero exit needs no separate guard: the part is
// still `completed` and stderr is concatenated into `output` (measured 1.18.19), so the
// JSON-parse guard rejects it exactly as it rejects `--help` usage. A refusal
// (`ok: false`) and a `main-thread` dispatch carry no `execution: "task"` and stay
// silent. `rule`/`run` come from the envelope — no stage list lives here. The appended
// part is ephemeral (measured: outbound request only, storage untouched), so the
// reminder rides every LLM call in the window instead of attaching once — the failure
// mode is silence, so repeating is strictly safer.
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
  linkSkills()
  return {
    config: async (config) => {
      try {
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
        armed = true
      } catch (e) {
        // Fail loud and closed: opencode swallows plugin throws (measured), a banner on
        // stderr and the skills vanishing are the symptoms left. The `armed` flag stays
        // false, so any judgment verb is hard-blocked in tool.execute.before below.
        unlinkSkills()
        console.error(
          `veripower: TRUST BOUNDARY GATE NOT INSTALLED (${e}). Judgment verbs ` +
            `(kernel.py pin/reopen/signoff) are BLOCKED for this session and VeriPower's ` +
            `skills were unregistered. Restart opencode or reinstall the plugin.`,
        )
      }
    },
    "tool.execute.before": async (_input, output) => {
      const cmd = typeof output.args?.command === "string" ? output.args.command : ""
      if (!JUDGMENT_VERB.test(cmd)) return
      if (!armed) {
        throw new Error(
          "veripower: judgment-verb gate not installed — this call is blocked rather " +
            "than run ungated. Restart opencode and retry; the consent prompt must " +
            "appear before this command runs.",
        )
      }
      output.args.command = `: "${SENTENCE}" ; ${cmd}`
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
