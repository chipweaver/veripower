import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, "../..")
const SKILLS_DIR = path.join(ROOT, "skills")

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
  // Judgment commands require the approval rules to be installed successfully.
  let armed = false
  return {
    config: async (config) => {
      armed = false
      try {
        config.permission = config.permission || {}
        gate(config.permission)
        config.permission.external_directory =
          typeof config.permission.external_directory === "string"
            ? { "*": config.permission.external_directory }
            : config.permission.external_directory || {}
        config.permission.external_directory[`${ROOT}/**`] = "allow"
        for (const agent of Object.values(config.agent || {})) {
          if (typeof agent.permission === "object" && agent.permission !== null) {
            gate(agent.permission)
          }
        }
        config.skills = config.skills || {}
        config.skills.paths = [...new Set([...(config.skills.paths || []), SKILLS_DIR])]
        armed = true
      } catch (e) {
        console.error(
          `veripower: TRUST BOUNDARY GATE NOT INSTALLED (${e}). Judgment verbs ` +
            `(kernel.py pin/reopen/signoff) are BLOCKED for this session. ` +
            `Restart opencode or reinstall the plugin.`,
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
