"""Dispatch context survives executor launch and ends at the next kernel action."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KERNEL_PATHS = ["kernel.py", '"/plugin path/kernel.py"', "'/plugin path/kernel.py'"]


@pytest.mark.parametrize("execution", ["task", "main-thread", None])
@pytest.mark.parametrize("kernel", KERNEL_PATHS)
def test_claude_reports_only_background_dispatch_context(execution, kernel):
    result = {"ok": True, "rule": "synthesis", "run": 3, "execution": execution}
    event = {
        "tool_input": {"command": f"python3 {kernel} dispatch --module example"},
        "tool_response": {"stdout": json.dumps(result)},
    }
    p = subprocess.run(
        [sys.executable, str(ROOT / ".claude/loop_after_dispatch.py")],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=True,
    )
    if execution == "task":
        context = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "synthesis" in context and "3" in context
    else:
        assert not p.stdout


@pytest.mark.skipif(not shutil.which("node"), reason="node is unavailable")
@pytest.mark.parametrize("dispatch_kernel", KERNEL_PATHS)
@pytest.mark.parametrize("next_kernel", KERNEL_PATHS)
def test_opencode_keeps_context_until_the_next_kernel_action(
    dispatch_kernel, next_kernel
):
    program = r"""
import assert from 'node:assert/strict';
const {default: plugin} = await import(process.argv[1]);
const histories={parent:[],child:[]};
async function restore() {
  return plugin.server({client:{session:{async messages({path,throwOnError}) {
    assert.equal(throwOnError,true);
    return {data:histories[path.id]};
  }}}});
}
let hooks=await restore();
const response=JSON.stringify({ok:true,execution:'task',rule:'synthesis',run:3});
const tool=(command,output=response,status='completed') => ({
  info:{role:'assistant'},parts:[{type:'tool',tool:'bash',
    state:{status,input:{command},output}}],
});
const messages=[{info:{role:'user'},parts:[{type:'text',text:'Continue the design task'}]},
  tool(`python3 ${process.argv[2]} dispatch --module example`)];
async function inspect(input,expected,sessionID='parent') {
  histories[sessionID]=input;
  const original=structuredClone(input);
  const output={system:[]};
  await hooks['experimental.chat.system.transform']({sessionID},output);
  const notices=output.system.filter(text=>text.startsWith('veripower loop:'));
  assert.equal(notices.length,expected);
  if(expected) assert.ok(notices[0].includes('synthesis') && notices[0].includes('3'));
  assert.deepEqual(input,original);
}
await inspect(messages,1);
messages.push({info:{role:'assistant'},parts:[{type:'tool',tool:'task',
  state:{status:'completed',input:{background:true},output:'executor started'}}]});
await inspect(messages,1);
hooks=await restore();
await inspect(messages,1);
await inspect([{info:{role:'user'},parts:[{type:'text',text:'child task'}]}],0,'child');
const decide=`python3 ${process.argv[3]} decide --module example`;
await inspect([...messages,tool(decide,'{"action":"YIELD"}')],0);
await inspect([...messages,tool(decide,'refused','error')],0);
for (const output of ['help text','not JSON',JSON.stringify({execution:'main-thread'}),JSON.stringify({ok:false})]) {
  await inspect([tool(`python3 ${process.argv[2]} dispatch --module example`,output)],0);
}
await inspect([tool(`python3 ${process.argv[2]} dispatch --module example`,response,'error')],0);

"""
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            program,
            (ROOT / ".opencode/plugins/veripower.js").as_uri(),
            dispatch_kernel,
            next_kernel,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="node is unavailable")
def test_deepseek_dispatch_context_preserves_the_host_decision():
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
for (const kernel of JSON.parse(process.argv[2])) {
  for (const execution of ['task','main-thread']) {
    for (const kind of ['accept','block']) {
      const downstream = {kind, feedback:[{type:'text',text:'host policy'}],
        additionalContexts:[{role:'user',content:[{type:'text',text:'existing context'}]}]};
      const original = structuredClone(downstream);
      const result = {content:[{type:'text',text:JSON.stringify({execution,rule:'synthesis',run:3})}]};
      const output = await hook({name:'bash',arguments:{command:`python3 ${kernel} dispatch --module example`}},
        result, async () => downstream);
      assert.equal(output.kind,kind);
      assert.deepEqual(output.feedback,original.feedback);
      assert.deepEqual(downstream,original);
      assert.deepEqual(output.additionalContexts.slice(execution === 'task' ? 1 : 0),original.additionalContexts);
      if (execution === 'task') {
        assert.equal(output.additionalContexts.length,2);
        assert.ok(output.additionalContexts[0].content[0].text.includes('synthesis'));
      } else assert.equal(output,downstream);
    }
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
            json.dumps(KERNEL_PATHS),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
