import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BINARY, PLUGIN, WORKDIR = sys.argv[1:]
ROOT = pathlib.Path(WORKDIR)
ROOT.mkdir(exist_ok=True)
requests = []
phase = {"parent": 0, "child": 0}
child_done = threading.Event()
child_requests = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "/count_tokens" in self.path:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"input_tokens":1}')
            return
        requests.append(b)
        users = " ".join(
            str(m.get("content")) for m in b.get("messages", []) if m["role"] == "user"
        )
        child = "CLAUDE_CHILD_PROBE" in users and "CLAUDE_PARENT_PROBE" not in users
        role = "child" if child else "parent"
        n = phase[role]
        phase[role] += 1
        if child:
            child_requests.append(b)
            if n == 0:
                name = "Skill"
                args = {"skill": "veripower:lint-cdc"}
                answer = None
            else:
                time.sleep(0.2)
                child_done.set()
                name = None
                args = None
                answer = "CLAUDE_CHILD_DONE"
        elif n == 0:
            name = "Skill"
            args = {"skill": "veripower:design-flow"}
            answer = None
        elif n == 1:
            name = "Agent"
            args = {
                "subagent_type": "general-purpose",
                "description": "native child fixture",
                "run_in_background": True,
                "prompt": "CLAUDE_CHILD_PROBE: load lint-cdc and finish.",
            }
            answer = None
        elif n == 2:
            name = None
            args = None
            answer = "parent waiting"
        else:
            name = None
            args = None
            answer = "parent resumed after child"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        events = [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": f"msg_{role}_{n}",
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": b.get("model"),
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                },
            )
        ]
        if name:
            events += [
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {
                            "type": "tool_use",
                            "id": f"tool_{role}_{n}",
                            "name": name,
                            "input": {},
                        },
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps(args),
                        },
                    },
                ),
            ]
        else:
            events += [
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": answer},
                    },
                ),
            ]
        events += [
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": "tool_use" if name else "end_turn",
                        "stop_sequence": None,
                    },
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
        for name, event in events:
            self.wfile.write(
                ("event: " + name + "\ndata: " + json.dumps(event) + "\n\n").encode()
            )
        self.wfile.flush()


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
env = os.environ.copy()
env["ANTHROPIC_API_KEY"] = "fixture"
env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
env["CLAUDE_CONFIG_DIR"] = str(ROOT / "config")
env.pop("ANTHROPIC_AUTH_TOKEN", None)
try:
    p = subprocess.run(
        [
            BINARY,
            "-p",
            "CLAUDE_PARENT_PROBE: run the native child fixture.",
            "--model",
            "sonnet",
            "--output-format",
            "stream-json",
            "--verbose",
            "--plugin-dir",
            PLUGIN,
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--allowedTools",
            "Skill",
            "Agent",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    (ROOT / "stdout.jsonl").write_text(p.stdout)
    (ROOT / "stderr.txt").write_text(p.stderr)
    print(
        "exit",
        p.returncode,
        "phases",
        phase,
        "child completed",
        child_done.is_set(),
        "requests",
        len(requests),
        flush=True,
    )
    assert p.returncode == 0, p.stderr[-1500:]
    assert requests and "VeriPower on Claude Code" in json.dumps(requests[0])
    assert child_done.is_set()
    assert child_requests and "VeriPower on Claude Code" in json.dumps(
        child_requests[0]
    )
    assert "CLAUDE_PARENT_PROBE" not in json.dumps(child_requests[0])
    expected = (
        (pathlib.Path(PLUGIN) / "skills/lint-cdc/SKILL.md")
        .read_text()
        .split("---", 2)[2]
        .strip()
    )
    assert any(
        expected in c.get("text", "")
        for b in child_requests
        for m in b["messages"]
        for c in m["content"]
        if isinstance(c, dict)
    )
    assert any(
        "CLAUDE_CHILD_DONE" in json.dumps(b)
        for b in requests
        if b not in child_requests
    )
    errors = [
        c
        for b in requests
        for m in b["messages"]
        for c in m["content"]
        if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error")
    ]
    assert not errors, errors
    print(
        "PASS: native parent and child adapter context, skill loading and background executor",
        flush=True,
    )
finally:
    (ROOT / "requests.json").write_text(json.dumps(requests, indent=2))
    server.shutdown()
    server.server_close()
