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
def test_opencode_reminds_at_native_background_launch():
    program = r"""
import assert from 'node:assert/strict';
const {default: plugin} = await import(process.argv[1]);
const hooks = await plugin.server();
const after = hooks['tool.execute.after'];
// The native subtask error path can call this hook without a result.
await after({tool:'task'},undefined);
for (const [tool,metadata,expected] of [
  ['task',{background:true,sessionId:'child',jobId:'child'},true],
  ['task',{sessionId:'child'},false],
  ['task',{background:false},false],
  ['bash',{background:true},false],
  ['skill',undefined,false],
]) {
  const input={tool,sessionID:'parent',callID:'call',args:{prompt:'self-contained task'}};
  const originalInput=structuredClone(input);
  const output={title:'host title',metadata,output:'<task state="running">host result</task>'};
  const original=structuredClone(output);
  await after(input,output);
  assert.deepEqual(input,originalInput);
  assert.deepEqual(output.metadata,original.metadata);
  assert.equal(output.title,original.title);
  assert.equal(output.output.startsWith(original.output),true);
  assert.equal(output.output.includes('kernel.py decide'),expected);
  if(!expected) assert.deepEqual(output,original);
}
"""
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            program,
            (ROOT / ".opencode/plugins/veripower.js").as_uri(),
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
