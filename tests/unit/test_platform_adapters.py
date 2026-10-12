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
const permission = {shell: policy, external_directory: 'deny'};
const original = structuredClone(permission);
const skills = [];
const hooks = {};
await plugin.setup({
  permission,
  skill: {async transform(editor) { editor({add(skill) { skills.push(skill); }}); }},
  session: {async hook(name, callback) { hooks[name] = callback; }},
});
assert.deepEqual(permission, original);
assert.equal(skills.length, 12);
for (const skill of skills) {
  assert.equal(skill.id, `veripower:${skill.name}`);
  assert.ok(skill.path.endsWith(`/skills/${skill.name}/SKILL.md`));
  assert.ok(skill.content.trim().length > 0);
}
assert.ok(hooks.context);

"""
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            program,
            (ROOT / ".opencode/plugins/veripower/server.js").as_uri(),
            policy,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
