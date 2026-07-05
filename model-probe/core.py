"""
core.py — framework for the Omnis model-probe test suite.

Dependency-free (Python standard library only). Provides:

  * Client      — a thin OpenAI-compatible Chat Completions client (urllib),
                  with first-class streaming SSE support.
  * ChatResult  — a normalized view of a (streamed or non-streamed) response:
                  text, tool_calls, reasoning, finish_reason, usage, timing.
  * Result      — the outcome of one check (status + summary + data).
  * @check(...)  — decorator registering a check function in a global registry.

A "check" is a function `def my_check(client) -> Result | list[Result]`.
See CLAUDE.md for how to add one.
"""

import json
import time
import urllib.request
import urllib.error

# ── Result statuses ──────────────────────────────────────────────────────────
PASS = "PASS"   # feature works as Omnis expects
FAIL = "FAIL"   # feature broken / unsupported (fails the run if check is critical)
WARN = "WARN"   # works partially / intermittently / weakly
INFO = "INFO"   # side information, no pass/fail judgement
SKIP = "SKIP"   # not applicable / not run
ERROR = "ERROR"  # the check itself crashed (treated like FAIL for exit code)

ALL_STATUSES = (PASS, FAIL, WARN, INFO, SKIP, ERROR)


class Result:
    """Outcome of a single check."""

    def __init__(self, status, summary, data=None):
        assert status in ALL_STATUSES, "bad status %r" % status
        self.status = status
        self.summary = summary
        self.data = data or {}

    def __repr__(self):
        return "Result(%s, %r)" % (self.status, self.summary)


# ── Check registry ───────────────────────────────────────────────────────────
class Check:
    def __init__(self, fn, name, category, critical, why):
        self.fn = fn
        self.name = name
        self.category = category
        self.critical = critical
        self.why = why


_REGISTRY = []


def check(name, category="misc", critical=False, why=""):
    """Register a check.

    name      human-readable title shown in the report.
    category  groups checks in the report; categories in OPT_IN_CATEGORIES
              (see probe.py) only run when explicitly enabled.
    critical  a FAIL/ERROR here makes the whole run fail (non-zero exit).
    why       one line explaining which Omnis feature this validates.
    """

    def deco(fn):
        _REGISTRY.append(Check(fn, name, category, critical, why))
        return fn

    return deco


def all_checks():
    return list(_REGISTRY)


# ── Normalized response ──────────────────────────────────────────────────────
class ChatResult:
    def __init__(self):
        self.ok = False
        self.status_code = None
        self.error = None            # str when the HTTP call failed
        self.text = ""
        self.reasoning = ""          # reasoning_content (thinking models)
        self.finish_reason = None
        self.tool_calls = []         # [{"id","name","arguments"}]
        self.usage = {}
        self.raw = None              # parsed json (non-stream) or [chunks] (stream)
        # streaming-only signals
        self.streamed = False
        self.saw_text_delta = False
        self.saw_tool_call_delta = False
        self.n_chunks = 0
        self.ttft = None             # seconds to first content/tool delta
        self.elapsed = None

    @property
    def tool_call_names(self):
        return [t["name"] for t in self.tool_calls if t.get("name")]

    @property
    def cached_tokens(self):
        u = self.usage or {}
        d = u.get("prompt_tokens_details") or {}
        return int(d.get("cached_tokens") or u.get("prompt_cache_hit_tokens") or 0)


# ── Client ───────────────────────────────────────────────────────────────────
class Client:
    """OpenAI-compatible Chat Completions client.

    base_url should include the version path, exactly like Omnis's
    `OPENAI_BASE_URL` (e.g. https://api.scaleway.ai/v1). The client appends
    `/chat/completions`, `/embeddings`, `/models`, `/model/info`.
    """

    def __init__(self, base_url, model, api_key="", timeout=120, headers=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.headers = headers or {}

    def _hdr(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        h.update(self.headers)
        return h

    # -- generic helpers --
    def get_json(self, path):
        """GET path → (status_code_or_None, parsed_json_or_error_text)."""
        try:
            req = urllib.request.Request(self.base_url + path, headers=self._hdr(), method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
                try:
                    return resp.status, json.loads(body)
                except Exception:
                    return resp.status, body[:2000]
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:2000]
        except Exception as e:
            return None, str(e)

    def post_json(self, path, body):
        """POST json body → (status_code_or_None, parsed_json_or_error_text)."""
        data = json.dumps(body).encode("utf-8")
        try:
            req = urllib.request.Request(self.base_url + path, data=data, headers=self._hdr(), method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                try:
                    return resp.status, json.loads(text)
                except Exception:
                    return resp.status, text[:2000]
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:2000]
        except Exception as e:
            return None, str(e)

    # -- chat --
    def chat(self, messages, tools=None, tool_choice=None, stream=False, model=None, **extra):
        body = {"model": model or self.model, "messages": messages}
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        body.update(extra)
        return self._chat_stream(body) if stream else self._chat_once(body)

    def _chat_once(self, body):
        r = ChatResult()
        t0 = time.time()
        try:
            req = urllib.request.Request(self.base_url + "/chat/completions",
                                         data=json.dumps(body).encode("utf-8"),
                                         headers=self._hdr(), method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                r.status_code = resp.status
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            r.status_code = e.code
            r.error = e.read().decode("utf-8", "replace")[:2000]
            return r
        except Exception as e:
            r.error = str(e)
            return r
        r.elapsed = time.time() - t0
        try:
            o = json.loads(raw)
        except Exception as e:
            r.error = "invalid JSON: %s" % e
            r.raw = raw[:2000]
            return r
        r.raw = o
        ch = (o.get("choices") or [{}])[0]
        msg = ch.get("message", {}) or {}
        r.finish_reason = ch.get("finish_reason")
        r.text = _content_text(msg.get("content"))
        r.reasoning = msg.get("reasoning_content") or ""
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {}) or {}
            r.tool_calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": fn.get("arguments")})
        r.usage = o.get("usage") or {}
        r.ok = True
        return r

    def _chat_stream(self, body):
        r = ChatResult()
        r.streamed = True
        t0 = time.time()
        pending = {}  # index -> {"id","name","args"}
        chunks = []
        try:
            req = urllib.request.Request(self.base_url + "/chat/completions",
                                         data=json.dumps(body).encode("utf-8"),
                                         headers=dict(self._hdr(), **{"Accept": "text/event-stream"}),
                                         method="POST")
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            r.status_code = resp.status
            for bline in resp:
                line = bline.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    o = json.loads(data)
                except Exception:
                    continue
                r.n_chunks += 1
                chunks.append(o)
                if o.get("usage"):
                    r.usage = o["usage"]
                for chc in (o.get("choices") or []):
                    delta = chc.get("delta", {}) or {}
                    cont = delta.get("content")
                    if isinstance(cont, list):
                        cont = _content_text(cont)
                    if cont:
                        if r.ttft is None:
                            r.ttft = time.time() - t0
                        r.saw_text_delta = True
                        r.text += cont
                    rc = delta.get("reasoning_content")
                    if rc:
                        r.reasoning += rc
                    for tc in (delta.get("tool_calls") or []):
                        if r.ttft is None:
                            r.ttft = time.time() - t0
                        r.saw_tool_call_delta = True
                        idx = tc.get("index", 0)
                        fn = tc.get("function", {}) or {}
                        p = pending.setdefault(idx, {"id": None, "name": None, "args": ""})
                        if tc.get("id"):
                            p["id"] = tc["id"]
                        if fn.get("name"):
                            p["name"] = fn["name"]
                        if fn.get("arguments"):
                            p["args"] += fn["arguments"]
                    if chc.get("finish_reason"):
                        r.finish_reason = chc["finish_reason"]
        except urllib.error.HTTPError as e:
            r.status_code = e.code
            r.error = e.read().decode("utf-8", "replace")[:2000]
            return r
        except Exception as e:
            r.error = str(e)
            return r
        r.elapsed = time.time() - t0
        for idx in sorted(pending):
            p = pending[idx]
            r.tool_calls.append({"id": p["id"], "name": p["name"], "arguments": p["args"]})
        r.raw = chunks
        r.ok = True
        return r


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, dict) and p.get("type", "text") in ("text", ""):
                out.append(p.get("text", ""))
        return "".join(out)
    return ""


# ── small formatting helpers usable by checks ────────────────────────────────
def fmt_ms(seconds):
    if seconds is None:
        return "n/a"
    return "%dms" % int(seconds * 1000)
