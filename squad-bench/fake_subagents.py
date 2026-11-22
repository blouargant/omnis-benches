#!/usr/bin/env python3
"""Fake OpenAI-compatible model server that answers for omnis sub-agents.

A squad's sub-agents are pointed at this server (fake_overlay.py); the leader
keeps a real model. Each sub-agent call gets the reply the current task's
script gives it, and every call is logged, so a bench measures the leader's
delegation alone. bench.py --fake drives it.

  fake_subagents.py PORT

Script: {"<agent>": [rule, ...]}. A rule has `reply` (text) or `status` (an
HTTP error), and optionally `when` (pattern on the request, as
scoring.match_rule), `times` (uses allowed), `if_new_request` (only for a
request unlike any that agent sent before in this task, see scoring.similar), `delay_ms` (default
300). The first usable rule wins; with none the reply is "No evidence found.".
"""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scoring

DEFAULT_REPLY = "No evidence found."
DEFAULT_DELAY_MS = 300
PREFIX = "fake-"


def agent_of(model):
    """The agent a model id stands for: `fake-<agent>` -> `<agent>`."""
    model = model or ""
    return model[len(PREFIX):] if model.startswith(PREFIX) else model


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def request_text(messages):
    """What the caller asked: the text of the last user message."""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            return _text(m.get("content"))
    return ""


def normalise(text):
    return scoring.normalise_request(text)


def _rule_error(r):
    if not isinstance(r.get("reply"), str) and not isinstance(r.get("status"), int):
        return "needs a `reply` (text) or a `status` (number)"
    when = r.get("when")
    if when is not None:
        if not isinstance(when, str):
            return "`when` must be text"
        if when.startswith("/") and when.endswith("/") and len(when) > 1:
            try:
                re.compile(when[1:-1])
            except re.error as e:
                return f"`when` is not a valid regex: {e}"
    for key in ("times", "delay_ms"):
        v = r.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
            return f"`{key}` must be a number >= 0"
    return None


def validate_script(script):
    """An error message, or None when the script is usable."""
    if not isinstance(script, dict):
        return "script must be an object mapping an agent name to a list of rules"
    for agent, rules in script.items():
        if not isinstance(rules, list):
            return f"rules of {agent!r} must be a list"
        for i, r in enumerate(rules):
            if not isinstance(r, dict):
                return f"rule {i} of {agent!r} must be an object"
            err = _rule_error(r)
            if err:
                return f"rule {i} of {agent!r}: {err}"
    return None


class Scenario:
    """One task's script and the requests each agent has sent so far."""

    def __init__(self, task, script):
        self.task = task
        self.script = script or {}
        self._lock = threading.Lock()
        self._used = {}      # (agent, rule index) -> uses
        self._seen = {}      # agent -> normalised requests, in order

    def answer(self, agent, request):
        norm = normalise(request)
        with self._lock:
            seen = self._seen.setdefault(agent, [])
            is_new = not any(scoring.similar(norm, e) for e in seen)
            picked = None
            for i, r in enumerate(self.script.get(agent) or []):
                if r.get("when") and not scoring.match_rule(r["when"], request):
                    continue
                if "times" in r and self._used.get((agent, i), 0) >= r["times"]:
                    continue
                if r.get("if_new_request") and not is_new:
                    continue
                picked = i
                self._used[(agent, i)] = self._used.get((agent, i), 0) + 1
                break
            seen.append(norm)
        if picked is None:
            return {"reply": DEFAULT_REPLY, "status": None, "delay_ms": DEFAULT_DELAY_MS, "rule": None}
        r = self.script[agent][picked]
        status = r.get("status") if isinstance(r.get("status"), int) else None
        return {"reply": None if status else r.get("reply"), "status": status,
                "delay_ms": r.get("delay_ms", DEFAULT_DELAY_MS), "rule": picked}


# ----------------------------------------------------------------------------- server
USAGE = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def send_json(self, obj, status=200):
        b = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def read_json(self):
        try:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return None

    def do_GET(self):
        s = self.server
        if self.path.rstrip("/").endswith("/calls"):
            with s.lock:
                self.send_json({"task": s.scenario.task, "calls": list(s.calls)})
        else:  # /v1/models
            self.send_json({"data": []})

    def do_POST(self):
        body = self.read_json()
        if not isinstance(body, dict):
            return self.send_json({"error": "body must be a JSON object"}, 400)
        if self.path.rstrip("/").endswith("/scenario"):
            return self.set_scenario(body)
        if self.path.rstrip("/").endswith("/chat/completions"):
            return self.chat(body)
        self.send_json({"error": "unknown path " + self.path}, 404)

    def set_scenario(self, body):
        err = validate_script(body.get("script"))
        if err:
            return self.send_json({"error": err}, 400)
        s = self.server
        with s.lock:
            s.scenario = Scenario(str(body.get("task") or ""), body["script"])
            s.calls = []
            s.t0 = time.monotonic()
        self.send_json({"ok": True})

    def chat(self, body):
        s = self.server
        agent = agent_of(body.get("model"))
        request = request_text(body.get("messages"))
        with s.lock:
            scenario, calls, t0 = s.scenario, s.calls, s.t0
            entry = {"agent": agent, "n": 1 + sum(1 for c in calls if c["agent"] == agent),
                     "request": request, "rule": None,
                     "started_ms": int((time.monotonic() - t0) * 1000), "ended_ms": None}
            calls.append(entry)
        a = scenario.answer(agent, request)
        time.sleep(max(0, a["delay_ms"]) / 1000)
        with s.lock:
            entry["rule"] = a["rule"]
            entry["ended_ms"] = int((time.monotonic() - t0) * 1000)
        if a["status"]:
            return self.send_json({"error": {"message": "scripted failure"}}, a["status"])
        msg = {"role": "assistant", "content": a["reply"]}
        model = body.get("model") or ""
        if not body.get("stream"):
            return self.send_json({"id": "fake", "object": "chat.completion", "model": model,
                                   "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                                   "usage": USAGE})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in ({"choices": [{"index": 0, "delta": msg}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": USAGE}):
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def serve(port):
    """The server, bound to 127.0.0.1 (port 0 picks a free one); call serve_forever()."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    srv.lock = threading.Lock()
    srv.scenario = Scenario("", {})
    srv.calls = []
    srv.t0 = time.monotonic()
    return srv


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    srv = serve(int(sys.argv[1]))
    print(f"fake sub-agents on http://127.0.0.1:{srv.server_address[1]}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
