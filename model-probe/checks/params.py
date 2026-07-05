"""Request-parameter & usage support checks (mostly side info)."""

from core import check, Result, PASS, WARN, INFO


@check("Usage accounting", category="params", critical=False,
       why="Omnis's cost/cache stats read usage.{prompt,completion}_tokens from responses.")
def usage_reported(client):
    r = client.chat(messages=[{"role": "user", "content": "Say hi."}], stream=False)
    if not r.ok:
        return Result(WARN, "call failed: %s" % (r.error or r.status_code))
    u = r.usage or {}
    if u.get("prompt_tokens") is not None and u.get("completion_tokens") is not None:
        return Result(PASS, "usage reported (prompt=%s, completion=%s)"
                      % (u.get("prompt_tokens"), u.get("completion_tokens")))
    return Result(WARN, "no token usage in response", data={"usage": u})


@check("Usage in streaming", category="params", critical=False,
       why="Omnis sets stream_options.include_usage; cost stats need a usage chunk at end-of-stream.")
def usage_in_stream(client):
    r = client.chat(messages=[{"role": "user", "content": "Say hi."}], stream=True)
    if r.error:
        return Result(WARN, "stream errored: %s" % r.error[:200])
    if (r.usage or {}).get("total_tokens") is not None:
        return Result(PASS, "usage chunk delivered in stream (total=%s)" % r.usage.get("total_tokens"))
    return Result(INFO, "no usage chunk in stream (include_usage may be ignored)")


@check("max_tokens", category="params", critical=False,
       why="Side info: does the endpoint honor max_tokens (truncation / finish_reason=length)?")
def max_tokens(client):
    r = client.chat(messages=[{"role": "user", "content": "Write a 500 word essay about the sea."}],
                    stream=False, max_tokens=16)
    if not r.ok:
        return Result(WARN, "endpoint rejected max_tokens (status=%s)" % r.status_code,
                      data={"error": (r.error or "")[:200]})
    if r.finish_reason == "length" or len((r.text or "").split()) <= 40:
        return Result(INFO, "max_tokens honored (finish_reason=%s)" % r.finish_reason)
    return Result(WARN, "max_tokens=16 but got a long answer", data={"finish_reason": r.finish_reason})


@check("temperature parameter", category="params", critical=False,
       why="Side info: endpoint accepts temperature without erroring.")
def temperature_param(client):
    r = client.chat(messages=[{"role": "user", "content": "Say hi."}], stream=False, temperature=0.2)
    if r.ok:
        return Result(INFO, "temperature accepted")
    return Result(WARN, "temperature rejected (status=%s)" % r.status_code, data={"error": (r.error or "")[:200]})
