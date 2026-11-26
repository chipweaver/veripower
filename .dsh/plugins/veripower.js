/** Register VeriPower skills and remind orchestration after native subagent launch. */

import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import * as skillFilesystem from '@deepseek-ai/dsh-skill-filesystem'

/** This file is `<repo>/.dsh/plugins/veripower.js`, so the skills root is two levels up. */
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const SKILLS_ROOT = resolve(ROOT, 'skills')

const SOURCE = { kind: 'veripower-dsh' }

const REMINDER = 'VeriPower: if you just launched a stage executor, '
  + 'call `kernel.py decide` now to schedule other ready work.'

export const name = 'veripower-dsh'
export const inject = ['tools', 'systemPrompt']

export function apply(ctx) {
  ctx.systemPrompt.section({
    name: 'veripower:tool-mapping',
    order: 0,
    text: 'VeriPower on DeepSeek Harness: load a bare skill X with skill using { name: X }. '
      + 'Launch a background executor with subagent using { prompt: P, description: "short task label" }; '
      + 'It returns immediately. Use wait_agent while waiting; confirm executor exit from the native finished notice. '
      + 'Run commands through bash and wait for background process results through job_output. '
      + `The kernel is python3 ${ROOT}/framework/scripts/kernel.py.`,
  })

  // An isolated provider keeps these skills out of the user's own roots and needs
  // no path in the deployment config: this file locates the checkout it ships in.
  ctx.plugin(skillFilesystem, {
    providerName: 'veripower',
    includeDefaultRoots: false,
    customSkillDirs: [SKILLS_ROOT],
  })

  ctx.on('tools/post-execute', async (exec, result, next) => {
    const downstream = await next()
    if (exec.name !== 'subagent' || result.isError) return downstream
    const context = createUserMessage({
      content: [{ type: 'text', text: REMINDER }],
      source: SOURCE,
    })
    return { ...downstream, additionalContexts: [context, ...downstream.additionalContexts ?? []] }
  })
}
