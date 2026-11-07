#!/usr/bin/env python3
"""Fake OpenAI-compatible model server for measuring omnis's fixed prompt.

Every request is recorded (system prompt + tool declarations). To reach the
whole agent tree it calls each sub-agent tool once per conversation, with
the request "PROBE:<agent>", so the sub-agent's first request names it. Then
it answers "ok". No real model is involved.

  fake_server.py PORT OUT.jsonl AGENT_NAMES_FILE
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, OUT, NAMES = int(sys.argv[1]), sys.argv[2], sys.argv[3]
AGENTS = set(open(NAMES).read().split())
lock = threading.Lock()


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def who(messages):
    for m in messages:
        if m.get("role") == "user":
            t = text_of(m.get("content"))
            for tag in ("PROBE-ROOT:", "PROBE:"):
                i = t.find(tag)
                if i >= 0:
                    return t[i + len(tag):].split()[0].strip('"}')
    return "?"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # /v1/models
        self.send_json({"data": [{"id": "probe"}]})

    def send_json(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body.get("messages", [])
        tools = body.get("tools") or []
        names = [t.get("function", {}).get("name", "") for t in tools]
        system = "".join(text_of(m.get("content")) for m in msgs if m.get("role") == "system")
        agent = who(msgs)
        with lock, open(OUT, "a") as f:
            f.write(json.dumps({"agent": agent, "n_messages": len(msgs), "system": system, "tools": tools}) + "\n")
        called = set()
        for m in msgs:
            for tc in m.get("tool_calls") or []:
                called.add(tc.get("function", {}).get("name"))
        todo = [n for n in names if n in AGENTS and n not in called]
        if todo:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_" + todo[0], "type": "function",
                "function": {"name": todo[0], "arguments": json.dumps({"request": "PROBE:" + todo[0]})}}]}
            finish = "tool_calls"
        else:
            msg = {"role": "assistant", "content": "ok"}
            finish = "stop"
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if not body.get("stream"):
            self.send_json({"id": "x", "object": "chat.completion", "model": "probe",
                            "choices": [{"index": 0, "message": msg, "finish_reason": finish}], "usage": usage})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        delta = dict(msg)
        if "tool_calls" in delta:
            delta["tool_calls"] = [dict(delta["tool_calls"][0], index=0)]
        for chunk in ({"choices": [{"index": 0, "delta": delta}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}):
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
