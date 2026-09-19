"""Dispatch context survives executor launch and ends at the next kernel action."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("execution", ["task", "main-thread", None])
def test_claude_reports_only_background_dispatch_context(execution):
    result = {"ok": True, "rule": "synthesis", "run": 3, "execution": execution}
    event = {
        "tool_input": {"command": "python3 kernel.py dispatch --module example"},
        "tool_response": {"stdout": json.dumps(result)},
    }
    p = subprocess.run(
        [sys.executable, str(ROOT / "hooks/loop_after_task_dispatch.py")],
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
def test_opencode_keeps_context_until_the_next_kernel_action():
    program = r"""
import assert from 'node:assert/strict';
const {default: plugin} = await import(process.argv[1]);
const hooks = await plugin();
const response = JSON.stringify({ok:true,execution:'task',rule:'synthesis',run:3});
const tool = (command, output=response) => ({type:'tool',tool:'bash',state:{status:'completed',input:{command},output}});
const messages=[{info:{role:'user'},parts:[{type:'text',text:'Continue the design task'}]},
 {info:{role:'assistant'},parts:[tool('python3 kernel.py dispatch --module example')]}];
const original=structuredClone(messages);
async function inspect(input,expected) {
 const output={messages:structuredClone(input)};
 await hooks['experimental.chat.messages.transform']({},output);
 const notices=output.messages.flatMap(m=>m.parts).filter(p=>p.type==='text' && p.text.startsWith('veripower loop:'));
 assert.equal(notices.length,expected);
 if(expected) assert.ok(notices[0].text.includes('synthesis') && notices[0].text.includes('3'));
 const dispatch=output.messages[1].parts.find(p=>p.type==='tool');
 assert.equal(dispatch.state.output,response);
}
await inspect(messages,1);
messages.push({info:{role:'assistant'},parts:[{type:'tool',tool:'task',state:{status:'completed',input:{background:true},output:'executor started'}}]});
await inspect(messages,1);
await inspect(messages,1);
messages.push({info:{role:'assistant'},parts:[tool('python3 kernel.py decide --module example','{"action":"YIELD"}') ]});
await inspect(messages,0);
assert.deepEqual(messages.slice(0,2),original);
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
