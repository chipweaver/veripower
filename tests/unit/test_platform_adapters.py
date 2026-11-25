"""Plugin integration preserves the host's permission configuration."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not shutil.which("node"), reason="node is unavailable")
@pytest.mark.parametrize("policy", ["allow", "ask", "deny"])
def test_opencode_registers_skills_without_changing_permissions(policy):
    program = r"""
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const {default: plugin} = await import(process.argv[1]);
const policy = process.argv[2];
const config = {
  permission: {bash: policy, external_directory: 'deny'},
  agent: {general: {permission: {bash: policy}}},
  skills: {paths: ['/existing/skills']},
};
const original = structuredClone(config);
const hooks = await plugin.server({client: {session: {async messages({path,throwOnError}) {
  assert.equal(throwOnError,true);
  assert.ok(['parent','child'].includes(path.id));
  return {data:[]};
}}}});
await hooks.config(config);
await hooks.config(config);
assert.deepEqual(config.permission,original.permission);
assert.deepEqual(config.agent,original.agent);
assert.deepEqual(config.skills.paths,[...original.skills.paths,
  fileURLToPath(new URL('../../skills',process.argv[1]))]);
for (const sessionID of ['parent','child',undefined]) {
  const output={system:['host instructions']};
  await hooks['experimental.chat.system.transform']({sessionID},output);
  assert.equal(output.system[0],'host instructions');
  assert.equal(output.system.length,2);
  assert.ok(output.system[1].includes('VeriPower on OpenCode 1'));
  assert.ok(output.system[1].includes('{ name: X }'));
}

"""
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            program,
            (ROOT / ".opencode/plugins/veripower.js").as_uri(),
            policy,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
