/** Register VeriPower skills and provide post-dispatch scheduling context. */

import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import * as skillFilesystem from '@deepseek-ai/dsh-skill-filesystem'

/** This file is `<repo>/.dsh/plugins/veripower.js`, so the skills root is two levels up. */
const SKILLS_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..', 'skills')

const SOURCE = { kind: 'plugin', plugin: 'veripower-dsh' }

const DISPATCH = /kernel\.py\s+dispatch\b/

const REMINDER = (rule, run) =>
  `veripower loop: after the executor for \`${rule}\` run ${run} has started, `
  + 'call `kernel.py decide` to schedule other ready work.'

/** The shell command a bash execution carries. */
function commandOf(exec) {
  const command = exec.arguments?.command
  return typeof command === 'string' ? command : ''
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
