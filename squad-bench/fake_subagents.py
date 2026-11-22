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
request that agent has not sent before in this task), `delay_ms` (default
300). The first usable rule wins; with none the reply is "No evidence found.".
"""
import os
import sys
import threading

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
    return " ".join((text or "").lower().split())


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
            if not isinstance(r.get("reply"), str) and not isinstance(r.get("status"), int):
                return f"rule {i} of {agent!r} needs a `reply` (text) or a `status` (number)"
    return None


class Scenario:
    """One task's script and the requests each agent has sent so far."""

    def __init__(self, task, script):
        self.task = task
        self.script = script or {}
        self._lock = threading.Lock()
        self._used = {}      # (agent, rule index) -> uses
        self._seen = {}      # agent -> set of normalised requests

    def answer(self, agent, request):
        norm = normalise(request)
        with self._lock:
            seen = self._seen.setdefault(agent, set())
            picked = None
            for i, r in enumerate(self.script.get(agent) or []):
                if r.get("when") and not scoring.match_rule(r["when"], request):
                    continue
                if "times" in r and self._used.get((agent, i), 0) >= r["times"]:
                    continue
                if r.get("if_new_request") and norm in seen:
                    continue
                picked = i
                self._used[(agent, i)] = self._used.get((agent, i), 0) + 1
                break
            seen.add(norm)
        if picked is None:
            return {"reply": DEFAULT_REPLY, "status": None, "delay_ms": DEFAULT_DELAY_MS, "rule": None}
        r = self.script[agent][picked]
        status = r.get("status") if isinstance(r.get("status"), int) else None
        return {"reply": None if status else r.get("reply"), "status": status,
                "delay_ms": r.get("delay_ms", DEFAULT_DELAY_MS), "rule": picked}
