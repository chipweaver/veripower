import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import SkillRegistry from '@deepseek-ai/dsh-skill';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import ToolRuntime, { defineTool } from '@deepseek-ai/dsh-tools';
import * as NativeExecutor from '@deepseek-ai/dsh-tool-executor-native';
import { createScope } from '@deepseek-ai/dsh-scope';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { releasedV4SessionFormatCodec } from '@deepseek-ai/dsh-session-format-v3-to-v4';
const adapter = await import(pathToFileURL(createRequire(process.argv[2]).resolve('veripower/dsh')).href);
const ctx = new Context();
await ctx.plugin(SkillRegistry);
await ctx.plugin(SystemPrompt);
await ctx.plugin(ToolRuntime);
await ctx.plugin(NativeExecutor);
await ctx.plugin(adapter);

try {
 const skills = await ctx.skills.list();
 assert.equal(skills.length, 12);
 const prompt = await ctx.systemPrompt.assemble();
 assert.ok(prompt.sections.some(s => s.name === 'veripower:tool-mapping'));
 const scope = createScope(ctx, {});
 const childPrompt = await ctx.systemPrompt.assemble({scope: scope.key});
 assert.deepEqual(childPrompt.sections, prompt.sections);
 await scope.dispose();
 ctx.tools.register(defineTool({
  name: 'subagent', description: 'fixture native launch result', parameters: {},
  output: {
   schema: {type: 'object', properties: {kind: {type: 'string', const: 'activation', required: true}, name: {type: 'string', required: true}}, additionalProperties: false},
   render: (_args, value) => [{type: 'text', text: `started subagent ${value.name}`}],
  },
  async execute() {return {kind: 'activation', name: 'fixture-review'};},
 }));
 for (const kind of ['accept', 'block']) {
  const dispose = ctx.on('tools/post-execute', () => ({kind, ...kind === 'block' ? {feedback: [{type: 'text', text: 'host refusal'}]} : {}}));
  const batch = await ctx.tools.execute({calls: [{type: 'tool-call', name: 'subagent', arguments: '{}', id: kind}], signal: new AbortController().signal});
  const result = batch.results[0].result;
  assert.equal(result.isError, kind === 'block');
  if (kind === 'accept') assert.deepEqual(result.value, {kind: 'activation', name: 'fixture-review'});
  else assert.equal(result.content[0].text, 'host refusal');
  const context = batch.additionalContexts[0];
  assert.ok(context.content[0].text.includes('kernel.py decide'));
  releasedV4SessionFormatCodec.encodeEvent({type: 'agent/inbox/spliced', seq: 0, time: Date.now(), data: {target: 'next-step', start: 0, inserted: [context]}});
  releasedV4SessionFormatCodec.encodeEvent({type: 'user/message', seq: 1, time: Date.now(), data: context});
  dispose();
 }
 console.log('PASS: native skills, scoped prompt, background-launch context and host decisions');
} finally {await ctx.fiber.dispose();}
