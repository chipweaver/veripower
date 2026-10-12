import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import SkillRegistry from '@deepseek-ai/dsh-skill';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import ToolRuntime, { defineTool } from '@deepseek-ai/dsh-tools';
import { createScope } from '@deepseek-ai/dsh-scope';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { releasedV4SessionFormatCodec } from '@deepseek-ai/dsh-session-format-v3-to-v4';
const adapter = await import(pathToFileURL(createRequire(process.argv[2]).resolve('veripower/dsh')).href);
const ctx = new Context();
await ctx.plugin(SkillRegistry);
await ctx.plugin(SystemPrompt);
await ctx.plugin(ToolRuntime);
await ctx.plugin(adapter);

try {
 const skills=await ctx.skills.list();

 assert.equal(skills.length,12);
 const prompt=await ctx.systemPrompt.assemble();
 assert.ok(prompt.sections.some(s=>s.name==='veripower:tool-mapping'));
 const scope=createScope(ctx,{});
 const childPrompt=await ctx.systemPrompt.assemble({scope:scope.key});
 assert.deepEqual(childPrompt.sections,prompt.sections);
 await scope.dispose();
 ctx.tools.register(defineTool({name:'bash',description:'fixture dispatch',parameters:{command:{type:'string',required:true}},output:{schema:{type:'string'},render:(args,value)=>[{type:'text',text:value}]},async execute(){return JSON.stringify({execution:'task',rule:'synthesis',run:3});}}));
 for (const kind of ['accept','block']) {
  const dispose=ctx.on('tools/post-execute',()=>({kind,...kind==='block'?{feedback:[{type:'text',text:'host refusal'}]}:{}}));
  const result=await ctx.tools.execute({name:'bash',arguments:{command:'python3 kernel.py dispatch --module fixture'},callId:kind,signal:new AbortController().signal});

  assert.equal(Boolean(result.isError),kind==='block');
  assert.ok(result.additionalContexts[0].content[0].text.includes('synthesis'));
  const context = result.additionalContexts[0];
  // Exercise the actual writer used when the deferred context enters live history.
  releasedV4SessionFormatCodec.encodeEvent({type:'agent/inbox/spliced',seq:0,time:Date.now(),data:{target:'next-step',start:0,inserted:[context]}});
  releasedV4SessionFormatCodec.encodeEvent({type:'user/message',seq:1,time:Date.now(),data:context});
  dispose();
 }
 console.log('PASS: native skills, scoped prompt, dispatch context persistence and host rejection');
} finally {await ctx.fiber.dispose();}
