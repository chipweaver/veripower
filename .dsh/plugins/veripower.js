/**
 * VeriPower's DeepSeek Harness adapter.
 *
 * Registers the module's own skills as an isolated `ctx.skills` provider, then
 * implements on dsh's interception points the two behaviours that ship as Claude
 * Code hooks (`hooks/hooks.json`) and as an opencode plugin
 * (`.opencode/plugins/veripower.js`): the ask-gate over the judgment verbs, and
 * the post-dispatch loop reminder. `framework/` and `skills/` are untouched — the
 * orchestrator reaches dsh's `skill` and `subagent` tools from the executor table
 * as written.
 *
 * Parity is with `hooks/ask_judgment_verbs.py` and
 * `hooks/loop_after_task_dispatch.py`; the gate reason and REMINDER are the
 * measured artifacts and are byte-identical to theirs.
 */

import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import * as skillFilesystem from '@deepseek-ai/dsh-skill-filesystem'

/** This file is `<repo>/.dsh/plugins/veripower.js`, so the skills root is two levels up. */
const SKILLS_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..', 'skills')

const SOURCE = { kind: 'plugin', plugin: 'veripower-dsh' }

/** Every `kernel.py <verb>` in a command, whatever path precedes it. */
const INVOCATION = /kernel\.py\s+([a-z]+)/g
/** The three verbs that move an oracle across the proposed -> human trust line. */
const GATED = new Set(['pin', 'reopen', 'signoff'])
const DISPATCH = /kernel\.py\s+dispatch\b/

const GATE_REASON = verb =>
  `veripower trust boundary: \`kernel.py ${verb}\` is a judgment verb. It is what `
  + `converts an LLM's own self-assessment into signoff-grade trust, so it is `
  + `yours to make, not the agent's. Approve only if you intended this call.`

const REMINDER = (rule, run) =>
  `veripower loop: \`${rule}\` run ${run} is in flight and this turn is not over. `
  + 'Your next call is `kernel.py decide` — now, before reaping it and before '
  + 'reporting. Make it even when you expect YIELD.'

/** The shell command a bash execution carries. */
function commandOf(exec) {
  const command = exec.arguments?.command
  return typeof command === 'string' ? command : ''
}

/**
 * The judgment verb `command` invokes, or undefined. A `--help` right after the
 * verb is not a call and exempts only itself, so a help invocation cannot clear a
 * real call later in the same command.
 */
function gatedVerb(command) {
  for (const match of command.matchAll(INVOCATION)) {
    const verb = match[1]
    if (!GATED.has(verb)) continue
    const next = command.slice(match.index + match[0].length).trimStart().split(/\s/, 1)[0]
    if (next !== '--help' && next !== '-h') return verb
  }
  return undefined
}

/** The dispatch envelope a settled bash result carries, or undefined. */
function envelope(result) {
  const text = (result?.content ?? []).filter(block => block?.type === 'text').map(block => block.text).join('')
  try {
    return JSON.parse(text)
  } catch {
    // `dispatch --help` prints argparse usage and a non-zero exit appends an exit
    // marker. Neither is an envelope, and neither is a fault to report.
    return undefined
  }
}

export const name = 'veripower-dsh'
export const inject = ['tools']

export function apply(ctx) {
  // An isolated provider keeps these skills out of the user's own roots and needs
  // no path in the deployment config: this file locates the checkout it ships in.
  ctx.plugin(skillFilesystem, {
    providerName: 'veripower',
    includeDefaultRoots: false,
    customSkillDirs: [SKILLS_ROOT],
  })

  // Fail-ASK: a gate against silent trust escalation must not vanish on its own
  // bug, so a command it cannot read still asks. Owning the decision means
  // returning without delegating.
  ctx.on('tools/pre-execute', async (exec, next) => {
    if (exec.name !== 'bash') return next()
    const verb = gatedVerb(commandOf(exec))
    if (verb === undefined) return next()
    return { kind: 'ask', reason: GATE_REASON(verb) }
  })

  // The reminder follows the dispatch it re-presents, so it cannot fail closed: a
  // shape it cannot read costs the reminder and nothing else. A `main-thread`
  // dispatch gets nothing — that Skill owns the rest of the turn by construction.
  ctx.on('tools/post-execute', async (exec, result, next) => {
    const out = exec.name === 'bash' && DISPATCH.test(commandOf(exec)) ? envelope(result) : undefined
    const downstream = await next()
    if (out?.execution !== 'task') return downstream
    const context = createUserMessage({
      content: [{ type: 'text', text: REMINDER(out.rule, out.run) }],
      source: SOURCE,
    })
    return { ...downstream, additionalContexts: [context, ...downstream.additionalContexts ?? []] }
  })
}
