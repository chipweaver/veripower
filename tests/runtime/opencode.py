import base64
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BINARY, PACKAGE, WORKDIR, POLICY = sys.argv[1:]
ROOT = pathlib.Path(WORKDIR)
ROOT.mkdir(exist_ok=True)
requests = []
phase = {"parent": 0, "child": 0}
child_done = threading.Event()
child_requests = []
(ROOT / "kernel.py").write_text(
    "import json,sys\nfrom pathlib import Path\nPath('executed').write_text('yes')\nprint(json.dumps({'execution':'task','rule':'synthesis','run':3} if sys.argv[1]=='dispatch' else {'action':'YIELD'}))\n"
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append(b)
        users = " ".join(
            str(m.get("content")) for m in b["messages"] if m["role"] == "user"
        )
        child = "VERIPOWER_CHILD" in users and "VERIPOWER_PARENT" not in users
        role = "child" if child else "parent"
        tools = [t["function"]["name"] for t in b.get("tools", [])]
        if not tools:
            name = None
            args = None
            answer = "fixture title"
        elif child:
            child_requests.append(b)
            n = phase[role]
            phase[role] += 1
            if n == 0:
                name = "skill"
                args = {"id": "veripower:lint-cdc"}
                answer = None
            else:
                time.sleep(0.4)
                child_done.set()
                name = None
                args = None
                answer = "VERIPOWER_CHILD_DONE"
        else:
            n = phase[role]
            phase[role] += 1
            choices = [
                ("skill", {"id": "veripower:design-flow"}),
                ("shell", {"command": f"python3 {ROOT}/kernel.py dispatch"}),
                (
                    "subagent",
                    {
                        "agent": "general",
                        "description": "native background fixture",
                        "background": True,
                        "prompt": "VERIPOWER_CHILD: load the lint-cdc skill and finish.",
                    },
                ),
                ("shell", {"command": f"python3 {ROOT}/kernel.py decide"}),
            ]
            if n < len(choices):
                name, args = choices[n]
                answer = None
            else:
                name = None
                args = None
                answer = (
                    "parent resumed after child"
                    if child_done.is_set()
                    else "parent waiting"
                )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        delta = {"role": "assistant"}
        if name:
            delta["tool_calls"] = [
                {
                    "index": 0,
                    "id": f"call_{role}_{phase[role]}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ]
        else:
            delta["content"] = answer
        for d, finish in [(delta, None), ({}, "tool_calls" if name else "stop")]:
            obj = {
                "id": f"chat_{role}_{phase[role]}",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "probe",
                "choices": [{"index": 0, "delta": d, "finish_reason": finish}],
            }
            self.wfile.write(("data: " + json.dumps(obj) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


model = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=model.serve_forever, daemon=True).start()
env = os.environ.copy()
for k in ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"]:
    env[k] = str(ROOT / k.lower())
    pathlib.Path(env[k]).mkdir(exist_ok=True)
env["OPENCODE_CONFIG_DIR"] = str(ROOT / "config")
pathlib.Path(env["OPENCODE_CONFIG_DIR"]).mkdir(exist_ok=True)
env["OPENCODE_CONFIG_PROJECT_DISABLE"] = "true"
env["OPENCODE_PASSWORD"] = "local-runtime-test"
env["OPENCODE_DISABLE_MODELS_FETCH"] = "true"
env["PROBE_API_KEY"] = "fixture"
config = {
    "plugins": ["veripower@file:" + PACKAGE],
    "model": "fixture/probe",
    "providers": {
        "fixture": {
            "env": ["PROBE_API_KEY"],
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": f"http://127.0.0.1:{model.server_port}/v1"},
            "models": {
                "probe": {
                    "name": "probe",
                    "limit": {"context": 65536, "output": 4096},
                    "capabilities": {"tools": True},
                }
            },
        }
    },
    "permissions": [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "shell", "resource": "*", "effect": POLICY},
    ],
}
env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
log = (ROOT / "server.log").open("w")
p = subprocess.Popen(
    [BINARY, "serve", "--hostname", "127.0.0.1", "--port", str(port), "--print-logs"],
    cwd=ROOT,
    env=env,
    stdout=log,
    stderr=log,
)


def req(ep, data=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}" + ep,
        data=None if data is None else json.dumps(data).encode(),
        headers={
            "Authorization": "Basic "
            + base64.b64encode(b"opencode:local-runtime-test").decode(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as res:
        text = res.read().decode()
        return json.loads(text) if text else None


try:
    deadline = time.monotonic() + 30
    while True:
        try:
            plugins = req("/api/plugin")
            v = [x for x in plugins["data"] if x.get("id") == "veripower"]
            if v:
                break
        except urllib.error.URLError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("plugin activation timeout")
        time.sleep(0.1)
    print("packed plugin", v, flush=True)
    assert v[0]["state"]["status"] == "active"
    skill = req("/api/skill")
    assert len([x for x in skill["data"] if x["id"].startswith("veripower:")]) == 12
    sess = req(
        "/api/session",
        {
            "agent": "build",
            "model": {"providerID": "fixture", "id": "probe"},
            "location": {"directory": str(ROOT)},
        },
    )["data"]["id"]
    print("session created", flush=True)
    req(
        "/api/session/" + sess + "/prompt",
        {"text": "VERIPOWER_PARENT: run the fixture background test."},
    )
    deadline = time.monotonic() + 25
    while not child_done.is_set() and time.monotonic() < deadline:
        time.sleep(0.1)
    time.sleep(0.5)
    print(
        "phases",
        phase,
        "child completed",
        child_done.is_set(),
        "requests",
        len(requests),
        flush=True,
    )
    assert child_done.is_set()
    assert child_requests and "VeriPower on OpenCode" in json.dumps(child_requests[0])
    assert "VERIPOWER_PARENT" not in json.dumps(child_requests[0])
    expected = next(
        s["content"].strip() for s in skill["data"] if s["id"] == "veripower:lint-cdc"
    )
    assert any(
        expected in m["content"]
        for b in child_requests
        for m in b["messages"]
        if m["role"] == "tool" and isinstance(m["content"], str)
    )
    parent = [b for b in requests if "VERIPOWER_PARENT" in json.dumps(b)]
    assert any("veripower loop:" in json.dumps(b) for b in parent) == (
        POLICY == "allow"
    )
    assert (ROOT / "executed").exists() == (POLICY == "allow")
    assert any("VERIPOWER_CHILD_DONE" in json.dumps(b) for b in parent)
    print(
        "PASS: package activation, 12 skills, fresh child mapping, background completion and parent reminder",
        flush=True,
    )
finally:
    (ROOT / "requests.json").write_text(json.dumps(requests, indent=2))
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    log.close()
    model.shutdown()
    model.server_close()
