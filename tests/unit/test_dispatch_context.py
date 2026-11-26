"""Adapters deliver scheduling context after native background executor launch."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("status", ["async_launched", "completed", "remote_launched"])
def test_claude_reminds_only_after_background_launch(status):
    event = {
        "hook_event_name": "PostToolUse",
        "tool_response": {"status": status},
    }
    p = subprocess.run(
        [sys.executable, str(ROOT / ".claude/adapter.py")],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=True,
    )
    if status in ("async_launched", "remote_launched"):
        output = json.loads(p.stdout)["hookSpecificOutput"]
        assert output["hookEventName"] == "PostToolUse"
        assert "kernel.py decide" in output["additionalContext"]
    else:
        assert not p.stdout


@pytest.mark.skipif(not shutil.which("node"), reason="node is unavailable")
def test_opencode_reminds_after_native_background_launch():
    program = r"""
import assert from 'node:assert/strict';
const {default: plugin} = await import(process.argv[1]);
let after;
await plugin.setup({
 skill: {async transform(cb) { cb({add() {}}); }},
 session: {async hook() {}},
 tool: {async hook(name, cb) { assert.equal(name,'execute.after'); after=cb; }},
});
const cases = [
 {tool:'subagent',status:'completed',result:{output:{sessionID:'child',status:'running',output:'host text'},content:[{type:'text',text:'host text'},{type:'file',uri:'file:///fixture',mime:'text/plain'}],metadata:{sessionID:'child',status:'running'}}},
 {tool:'subagent',status:'completed',result:{output:{sessionID:'child',status:'running',output:'host text'},content:'host text'}},
 {tool:'subagent',status:'error',error:{message:'host denied'}},
 {tool:'shell',status:'completed',result:{output:'plain stdout',content:[{type:'text',text:'plain stdout'}]}},
];
for (const event of cases) {
 const original=structuredClone(event);
 await after(event);
 const expected=event.tool==='subagent' && event.status==='completed';
 if (!expected) {assert.deepEqual(event,original);continue;}
 assert.deepEqual(event.result.output,original.result.output);
 assert.deepEqual(event.result.metadata,original.result.metadata);
 const previous=typeof original.result.content==='string' ? [{type:'text',text:original.result.content}] : original.result.content;
 assert.deepEqual(event.result.content.slice(0,-1),previous);
 assert.ok(event.result.content.at(-1).text.includes('kernel.py decide'));
}
"""
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            program,
            (ROOT / ".opencode/plugins/veripower/server.js").as_uri(),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="node is unavailable")
def test_deepseek_launch_context_preserves_the_host_decision():
    # Only the two external imports are substituted. Native SDK integration is
    # checked separately; this test exercises the shipped adapter's callback.
    program = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import * as path from 'node:path';
import * as url from 'node:url';
const adapter = new vm.SourceTextModule(readFileSync(new URL(process.argv[1]),'utf8'), {
  initializeImportMeta(meta) { meta.url = process.argv[1]; }
});
const imports = {
  'node:path': path,
  'node:url': url,
  '@deepseek-ai/dsh-llm': {createUserMessage: value => value},
  '@deepseek-ai/dsh-skill-filesystem': {apply() {}},
};
await adapter.link(specifier => {
  const exports = imports[specifier];
  return new vm.SyntheticModule(Object.keys(exports), function() {
    for (const [name,value] of Object.entries(exports)) this.setExport(name,value);
  });
});
await adapter.evaluate();
const handlers = {};
adapter.namespace.apply({
  plugin() {},
  systemPrompt: {section() {}},
  on(name, handler) { handlers[name] = handler; },
});
const hook = handlers['tools/post-execute'];
for (const kind of ['accept','block']) {
  for (const [name,result,expected] of [
    ['subagent',{isError:false,value:{kind:'activation',name:'review'},content:[{type:'text',text:'started subagent review'}]},true],
    ['subagent',{isError:true,error:{message:'host denied'},content:[{type:'text',text:'host denied'}]},false],
    ['bash',{isError:false,value:'plain stdout',content:[{type:'text',text:'plain stdout'}]},false],
  ]) {
    const downstream={kind,feedback:[{type:'text',text:'host policy'}],additionalContexts:[{role:'user',content:[{type:'text',text:'existing context'}]}]};
    const original=structuredClone(downstream);
    const originalResult=structuredClone(result);
    const output=await hook({name,arguments:{prompt:'self-contained task'}},result,async()=>downstream);
    assert.equal(output.kind,kind);
    assert.deepEqual(output.feedback,original.feedback);
    assert.deepEqual(result,originalResult);
    assert.deepEqual(downstream,original);
    assert.deepEqual(output.additionalContexts.slice(expected?1:0),original.additionalContexts);
    if(expected) assert.ok(output.additionalContexts[0].content[0].text.includes('kernel.py decide'));
    else assert.equal(output,downstream);
  }
}

"""
    subprocess.run(
        [
            "node",
            "--experimental-vm-modules",
            "--input-type=module",
            "-e",
            program,
            (ROOT / ".dsh/plugins/veripower.js").as_uri(),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
