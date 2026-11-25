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

BINARY, PACKAGE, WORKDIR, SCENARIO = sys.argv[1:]
POLICY = SCENARIO if SCENARIO in {"allow", "deny", "ask"} else "allow"
ROOT = pathlib.Path(WORKDIR)
ROOT.mkdir(exist_ok=True)
requests = []
phase = {"parent": 0, "child": 0}
child_done = threading.Event()
child_requests = []
child_started = threading.Event()
child_aborted = threading.Event()
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
            child_started.set()
            if SCENARIO == "abort":
                child_aborted.wait(timeout=20)
                return
            n = phase[role]
            phase[role] += 1
            if n == 0:
                name = "skill"
                args = {"name": "lint-cdc"}
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
                ("skill", {"name": "design-flow"}),
                (
                    "bash",
                    {
                        "command": f"python3 {ROOT}/kernel.py dispatch",
                        "description": "Dispatch fixture",
                    },
                ),
                (
                    "task",
                    {
                        "subagent_type": "general",
                        "description": "native background fixture",
                        "background": True,
                        "prompt": "VERIPOWER_CHILD: load the lint-cdc skill and finish.",
                    },
                ),
                (
                    "bash",
                    {
                        "command": f"python3 {ROOT}/kernel.py decide",
                        "description": "Schedule fixture",
                    },
                ),
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
env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "true"
env["OPENCODE_SERVER_PASSWORD"] = "local-runtime-test"
env["OPENCODE_DISABLE_MODELS_FETCH"] = "true"
env["PROBE_API_KEY"] = "fixture"
env["OPENCODE_SERVER_USERNAME"] = "opencode"
env["OPENCODE_TEST_HOME"] = str(ROOT / "home")
env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] = "true"
env["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = "true"
env["OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS"] = (
    "false" if SCENARIO == "background-off" else "true"
)
config = {
    "plugin": ["veripower@file:" + PACKAGE],
    "model": "fixture/probe",
    "provider": {
        "fixture": {
            "env": ["PROBE_API_KEY"],
            "npm": "@ai-sdk/openai-compatible",
            "options": {"baseURL": f"http://127.0.0.1:{model.server_port}/v1"},
            "models": {
                "probe": {
                    "name": "probe",
                    "limit": {"context": 65536, "output": 4096},
                    "tool_call": True,
                }
            },
        }
    },
    "permission": {"*": "allow", "bash": POLICY},
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
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        request, timeout=20
    ) as res:
        text = res.read().decode()
        return json.loads(text) if text else None


try:
    deadline = time.monotonic() + 45
    while "opencode server listening" not in (ROOT / "server.log").read_text():
        if p.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError((ROOT / "server.log").read_text())
        time.sleep(0.1)
    req("/global/health")
    skill = req("/skill")
    installed = [x for x in skill if "/skills/" in x["location"]]
    assert len(installed) == 12, installed
    print("packed plugin: 12 installed skills", flush=True)
    sess = req("/session", {})["id"]
    req(
        "/session/" + sess + "/prompt_async",
        {
            "agent": "build",
            "model": {"providerID": "fixture", "modelID": "probe"},
            "parts": [
                {
                    "type": "text",
                    "text": "VERIPOWER_PARENT: run the fixture background test.",
                }
            ],
        },
    )
    refusals = 0
    resumed_after_abort = False
    parent_requests_before_resume = 0
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        for pending in req("/permission"):
            assert POLICY == "ask", pending
            req("/permission/" + pending["id"] + "/reply", {"reply": "reject"})
            refusals += 1
        if (
            SCENARIO == "abort"
            and child_started.is_set()
            and not child_aborted.is_set()
        ):
            children = req("/session/" + sess + "/children")
            assert len(children) == 1, children
            req("/session/" + children[0]["id"] + "/abort", {})
            child_aborted.set()
        parent = [b for b in requests if "VERIPOWER_PARENT" in json.dumps(b)]
        if SCENARIO == "abort" and child_aborted.is_set() and phase["parent"] >= 5:
            status = req("/session/status")
            if children[0]["id"] not in status and sess not in status:
                if not resumed_after_abort:
                    parent_requests_before_resume = len(parent)
                    req(
                        "/session/" + sess + "/prompt_async",
                        {
                            "agent": "build",
                            "model": {"providerID": "fixture", "modelID": "probe"},
                            "parts": [
                                {
                                    "type": "text",
                                    "text": "The host confirms the child was cancelled and has exited. Resume the parent.",
                                }
                            ],
                        },
                    )
                    resumed_after_abort = True
                elif len(parent) > parent_requests_before_resume:
                    break
        if (
            SCENARIO == "background-off"
            and phase["parent"] >= 5
            and sess not in req("/session/status")
        ):
            break
        if any("VERIPOWER_CHILD_DONE" in json.dumps(b) for b in parent):
            break
        if POLICY == "ask" and refusals and sess not in req("/session/status"):
            break
        time.sleep(0.1)
    print(
        "phases",
        phase,
        "child completed",
        child_done.is_set(),
        "requests",
        len(requests),
        flush=True,
    )
    assert (refusals > 0) == (POLICY == "ask")
    if POLICY == "ask":
        assert not child_done.is_set()
        assert not (ROOT / "executed").exists()
        assert phase["parent"] == 2
        print(
            "PASS: host approval rejection prevents execution and stops the turn",
            flush=True,
        )
        sys.exit(0)
    if SCENARIO == "abort":
        assert child_aborted.is_set()
        assert not child_done.is_set()
        child_messages = req("/session/" + children[0]["id"] + "/message")
        assert any(
            m["info"].get("error", {}).get("name") == "MessageAbortedError"
            for m in child_messages
        )
        assert resumed_after_abort and len(parent) > parent_requests_before_resume
        assert any(
            m["role"] == "system" and "VeriPower on OpenCode 1" in str(m.get("content"))
            for m in parent[-1]["messages"]
        )
        print(
            "PASS: host-confirmed child cancellation and explicit parent resumption",
            flush=True,
        )
        sys.exit(0)
    if SCENARIO == "background-off":
        assert not child_started.is_set()
        durable = req("/session/" + sess + "/message")
        assert (
            "Background subagents require OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true"
            in json.dumps(durable)
        )
        assert not any(
            "background" in t["function"].get("parameters", {}).get("properties", {})
            for b in parent
            for t in b.get("tools", [])
            if t["function"]["name"] == "task"
        )
        print(
            "PASS: background capability is absent and rejected when disabled",
            flush=True,
        )
        sys.exit(0)
    assert child_done.is_set()
    assert child_requests and any(
        m["role"] == "system" and "VeriPower on OpenCode 1" in str(m["content"])
        for m in child_requests[0]["messages"]
    )
    assert all(
        "VeriPower on OpenCode 1" not in str(m.get("content"))
        for b in requests
        for m in b["messages"]
        if m["role"] == "user"
    )
    assert "VERIPOWER_PARENT" not in json.dumps(child_requests[0])
    expected = next(s["content"].strip() for s in skill if s["name"] == "lint-cdc")
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
    durable = req("/session/" + sess + "/message")
    assert "veripower loop:" not in json.dumps(durable)
    assert "VeriPower on OpenCode 1" not in json.dumps(durable)
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
