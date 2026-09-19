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
const {default: plugin} = await import(process.argv[1]);
const policy = process.argv[2];
const config = {permission: {bash: {'*': policy, '*kernel.py*pin*': policy}, external_directory: 'deny'},
 agent: {general: {permission: {bash: policy}}}};
const original = structuredClone(config);
const hooks = await plugin();
await hooks.config(config);
assert.deepEqual(config.permission, original.permission);
assert.deepEqual(config.agent, original.agent);
assert.ok(config.skills.paths.length > 0);
const output = {args: {command: 'python3 /plugin/kernel.py pin --module M --help'}};
if (hooks['tool.execute.before']) await hooks['tool.execute.before']({}, output);
assert.equal(output.args.command, 'python3 /plugin/kernel.py pin --module M --help');
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
