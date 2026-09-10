"""Opt-in integration with real Codex and a scripted local Responses endpoint.

VERIPOWER_CODEX_TESTS=1 pytest -q tests/unit/test_codex_runtime.py
No model/API key or EDA license is used. Approval replies apply only to the
fixture kernel; this tests host mechanics, not model compliance or EDA quality.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from test_codex_adapter import setup

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get("VERIPOWER_CODEX_TESTS") != "1" or not shutil.which("codex"),
    reason="opt-in native Codex runtime probe",
)


def call(name, args, call_id="probe", namespace=None):
    item = {
        "id": f"fc_{call_id}",
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(args),
    }
    if namespace:
        item["namespace"] = namespace
    return item


def message(text="probe complete"):
    return {
        "id": "msg_probe",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def run_codex(tmp_path, responder, decision="decline"):
    """Drive one app-server turn; fixtures and hook overrides stay under tmp_path."""
    fixture = tmp_path / "plugin"
    (fixture / "framework/scripts").mkdir(parents=True)
    (fixture / "codex").mkdir()
    (fixture / "skills/design-flow").mkdir(parents=True)
    (fixture / "codex/instructions.md").write_text(
        (ROOT / "codex/instructions.md").read_text()
    )
    (fixture / "framework/scripts/kernel.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(tmp_path / 'executed')!r}).write_text('yes')\n"
        "print('fixture judgment executed')\n"
    )
    config = tmp_path / ".codex"
    (config / "rules").mkdir(parents=True)
    (config / "rules/veripower.rules").write_text(setup.rules_text(fixture))
    shutil.copyfile(ROOT / "codex/adapter.py", fixture / "codex/adapter.py")
    (config / "hooks.json").write_text(
        (ROOT / "codex/hooks.json").read_text().replace("${PLUGIN_ROOT}", str(fixture))
    )
    requests = []
    errors = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            try:
                item = responder(body, len(requests), fixture)
            except Exception as exc:
                errors.append(exc)
                item = message("fixture responder failed")
            events = [
                {"type": "response.created", "response": {"id": "response_probe"}},
                {"type": "response.output_item.added", "output_index": 0, "item": item},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "response_probe",
                        "status": "completed",
                        "output": [item],
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "total_tokens": 2,
                        },
                    },
                },
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in events:
                self.wfile.write(
                    (
                        "event: "
                        + event["type"]
                        + "\ndata: "
                        + json.dumps(event)
                        + "\n\n"
                    ).encode()
                )
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    args = [
        "codex",
        "app-server",
        "-c",
        'model_providers.veripower_probe={name="probe",'
        f'base_url="http://127.0.0.1:{server.server_port}/v1",'
        'wire_api="responses",requires_openai_auth=false}',
        "-c",
        f'projects.{json.dumps(str(tmp_path))}.trust_level="trusted"',
        "-c",
        "features.code_mode=false",
        "-c",
        "features.code_mode_only=false",
        "-c",
        "features.remote_plugin=false",
        "-c",
        "features.plugins=false",
    ]
    events = []
    inbox = queue.Queue()
    with (tmp_path / "stderr.log").open("w") as log:
        process = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True
        )

        def receive():
            for line in process.stdout:
                inbox.put(json.loads(line))

        threading.Thread(target=receive, daemon=True).start()

        def send(payload):
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()

        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "veripower_test", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            }
        )
        deadline = time.monotonic() + 40
        completed = False
        try:
            while time.monotonic() < deadline:
                try:
                    event = inbox.get(timeout=1)
                except queue.Empty:
                    continue
                events.append(event)
                if event.get("id") == 1 and "result" in event:
                    send({"method": "initialized", "params": {}})
                    send(
                        {
                            "id": 2,
                            "method": "thread/start",
                            "params": {
                                "cwd": str(tmp_path),
                                "model": "gpt-5.4",
                                "modelProvider": "veripower_probe",
                                "approvalPolicy": "on-request",
                                "approvalsReviewer": "user",
                                "sandbox": "workspace-write",
                                "ephemeral": True,
                                # Trust only this test invocation's self-authored fixtures;
                                # never persist trust or bypass command approvals.
                                "config": {"bypass_hook_trust": True},
                            },
                        }
                    )
                elif event.get("id") == 2 and "result" in event:
                    thread_id = event["result"]["thread"]["id"]
                    send(
                        {
                            "id": 3,
                            "method": "turn/start",
                            "params": {
                                "threadId": thread_id,
                                "input": [
                                    {
                                        "type": "text",
                                        "text": "Run the fixture test; spawn a fixture child if requested by the scripted test.",
                                    }
                                ],
                            },
                        }
                    )
                elif "id" in event and "method" in event:
                    assert event["method"] == "item/commandExecution/requestApproval", (
                        event
                    )
                    send({"id": event["id"], "result": {"decision": decision}})
                elif (
                    event.get("method") == "turn/completed"
                    and event["params"]["threadId"] == thread_id
                ):
                    completed = True
                    break
                elif "error" in event:
                    pytest.fail(str(event))
        finally:
            process.terminate()
            process.wait(timeout=5)
            server.shutdown()
            server.server_close()
    assert completed, (tmp_path / "stderr.log").read_text()
    assert not errors, errors
    return events, requests


@pytest.mark.parametrize("decision", ["accept", "decline"])
@pytest.mark.parametrize(
    "kernel",
    [
        "framework/scripts/kernel.py",
        "skills/design-flow/../../framework/scripts/kernel.py",
    ],
)
def test_judgment_gets_native_human_approval(tmp_path, decision, kernel):
    def response(_body, number, fixture):
        if number == 1:
            return call(
                "exec_command",
                {
                    "cmd": f"python3 {fixture}/{kernel} pin",
                    "workdir": str(tmp_path),
                    "yield_time_ms": 1000,
                },
            )
        return message()

    events, _ = run_codex(tmp_path, response, decision)
    approvals = [
        e for e in events if e.get("method") == "item/commandExecution/requestApproval"
    ]
    assert len(approvals) == 1
    assert setup.REASON.format(verb="pin") in approvals[0]["params"]["reason"]
    assert (tmp_path / "executed").exists() == (decision == "accept")


def test_fresh_native_child_receives_adapter_and_parent_waits(tmp_path):
    child_requests = []

    def response(body, _number, _fixture):
        inputs = body.get("input", [])
        is_child = any(
            item.get("role") == "user"
            and "VERIPOWER_CHILD_PROBE" in json.dumps(item.get("content"))
            for item in inputs
        )
        if is_child:
            child_requests.append(body)
            if not any(
                item.get("call_id") == "child_read"
                and item.get("type") == "function_call_output"
                for item in inputs
            ):
                return call(
                    "exec_command",
                    {
                        "cmd": f"cat {ROOT}/skills/lint-cdc/SKILL.md",
                        "workdir": str(tmp_path),
                    },
                    "child_read",
                )
            return message("child read the stage skill")
        outputs = {
            item.get("call_id"): item.get("output")
            for item in inputs
            if item.get("type") == "function_call_output"
        }
        if "spawn_probe" not in outputs:
            return call(
                "spawn_agent",
                {
                    "message": "VERIPOWER_CHILD_PROBE: read the supplied lint-cdc skill, then finish.",
                    "fork_context": False,
                },
                "spawn_probe",
                "multi_agent_v1",
            )
        if "wait_probe" not in outputs:
            spawned = json.loads(outputs["spawn_probe"])
            return call(
                "wait_agent",
                {"targets": [spawned["agent_id"]], "timeout_ms": 10000},
                "wait_probe",
                "multi_agent_v1",
            )
        return message("parent resumed after child")

    _, requests = run_codex(tmp_path, response)
    assert child_requests, "Codex did not start a child"
    assert "VeriPower on Codex" in json.dumps(child_requests[0])
    assert "Run the fixture test; spawn a fixture child" not in json.dumps(
        child_requests[0]
    )
    assert any(
        "child read the stage skill" in json.dumps(request)
        for request in requests
        if request not in child_requests
    )
