#!/usr/bin/env python3
"""Reproduction minimale : Devstral-Small perd ses tool calls en streaming+auto.

Stdlib uniquement. Credentials depuis le `.env` racine du repo :

    set -a; . ./.env; set +a
    python3 reports/gateway-devstral-small-tool-calling-2026-10-06-probe.py

Chaque requete porte un nonce : le cache de reponses de la gateway ne peut pas
rejouer un verdict anterieur (cf. CLAUDE.md, gotcha "x-litellm-cache-key").

Attendu sur le deploiement casse :
  nonstream   auto     -> finish=tool_calls, get_weather          OK
  stream      auto     -> finish=stop, AUCUN delta, out_tok=12    CASSE
  stream      required -> get_weather({"city": "Paris"})          OK
  stream      (named)  -> get_weather({"city": "Paris"})          OK
Et sur les voisins hosted_vllm du meme hote (temoins) : tout passe.
"""
import json
import os
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
KEY = os.environ.get("OPENAI_API_KEY", "")

WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}
PROMPT = "What is the weather in Paris? Use the get_weather tool."


def post(body):
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
    )
    try:
        return urllib.request.urlopen(req, timeout=180), None
    except urllib.error.HTTPError as exc:
        return None, (exc.code, exc.read()[:300].decode("utf8", "replace"))


def run(model, stream, tool_choice="auto", prompt=PROMPT):
    """Return a one-line summary of what the endpoint actually delivered."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "%s (nonce %s)" % (prompt, uuid.uuid4())}],
        "tools": [WEATHER],
        "tool_choice": tool_choice,
        "stream": stream,
    }
    if stream:
        body["stream_options"] = {"include_usage": True}

    resp, err = post(body)
    label = "%-26s %-10s tc=%-9s" % (model, "stream" if stream else "nonstream", tool_choice)
    if err:
        return "%s HTTP %s %s" % (label, err[0], err[1][:160])

    if not stream:
        data = json.load(resp)
        msg = data["choices"][0]["message"]
        return "%s finish=%-11s out_tok=%-4s calls=%s" % (
            label,
            data["choices"][0]["finish_reason"],
            data["usage"]["completion_tokens"],
            [t["function"]["name"] for t in (msg.get("tool_calls") or [])] or "NONE",
        )

    # Streaming: reassemble the tool-call deltas the way an OpenAI client would.
    acc, text, finish, usage = {}, [], None, None
    for raw in resp:
        line = raw.decode("utf8", "replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        chunk = json.loads(payload)
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices", []):
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
            delta = choice.get("delta", {})
            if delta.get("content"):
                text.append(delta["content"])
            for call in delta.get("tool_calls") or []:
                slot = acc.setdefault(call.get("index", 0), {"name": "", "args": ""})
                fn = call.get("function") or {}
                slot["name"] += fn.get("name") or ""
                slot["args"] += fn.get("arguments") or ""

    calls = ["%s(%s)" % (a["name"], a["args"][:40]) for _, a in sorted(acc.items())]
    return "%s finish=%-11s out_tok=%-4s calls=%s text=%r" % (
        label,
        finish,
        (usage or {}).get("completion_tokens"),
        calls or "NONE",
        "".join(text)[:60],
    )


def main():
    if not BASE or not KEY:
        raise SystemExit("set OPENAI_BASE_URL / OPENAI_API_KEY (source the root .env)")

    print("== Devstral-Small : le modele emet bien le tool call, le streaming+auto le perd ==")
    print(run("Devstral-Small", False, "auto"))
    print(run("Devstral-Small", True, "auto"))
    print(run("Devstral-Small", True, "required"))
    print(run("Devstral-Small", True, {"type": "function", "function": {"name": "get_weather"}}))

    print()
    print("== Le texte libre passe, lui : seul le tool call disparait ==")
    print(run("Devstral-Small", True, "auto", "Say hello in one sentence, no tools needed."))

    print()
    print("== Temoins : memes provider/hote/gateway, streaming+auto intact ==")
    for witness in ("ChapsVision", "Qwen3.6-27B-ChapsVision"):
        print(run(witness, True, "auto"))


if __name__ == "__main__":
    main()
