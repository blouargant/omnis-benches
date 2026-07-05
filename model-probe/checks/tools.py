"""Tool-calling (function-calling) checks — the heart of Omnis's agent loop.

Tool-calling decisions are sampled a few times so an intermittent failure is
reported as WARN rather than slipping through on a lucky PASS.
"""

from core import check, Result, PASS, FAIL, WARN, INFO
from ._helpers import weather_tool, discover_tool, WEATHER_MESSAGES, DISCOVER_MESSAGES, fraction

SAMPLES = 3


@check("Tool calling (non-streaming)", category="tools", critical=True,
       why="Omnis is an agent: the model must emit OpenAI tool_calls when given tools.")
def tool_call_nonstreaming(client):
    r = client.chat(messages=WEATHER_MESSAGES, tools=[weather_tool()], tool_choice="auto", stream=False)
    if not r.ok:
        return Result(FAIL, "request failed: %s" % (r.error or r.status_code))
    if "get_weather" in r.tool_call_names:
        return Result(PASS, "tool call returned (finish_reason=%s)" % r.finish_reason)
    return Result(FAIL, "no tool call (finish_reason=%s)" % r.finish_reason, data={"content": r.text[:200]})


@check("Tool calling (streaming)", category="tools", critical=True,
       why="Omnis streams every turn; tool calls must survive SSE. This is the exact GLM-5.2/Scaleway regression.")
def tool_call_streaming(client):
    ok = 0
    attempts = []
    for _ in range(SAMPLES):
        r = client.chat(messages=WEATHER_MESSAGES, tools=[weather_tool()], tool_choice="auto", stream=True)
        if r.error:
            return Result(FAIL, "stream errored: %s" % r.error[:200])
        good = r.saw_tool_call_delta and "get_weather" in r.tool_call_names
        ok += 1 if good else 0
        attempts.append({"finish_reason": r.finish_reason, "tool_calls": r.tool_call_names})
    if ok == SAMPLES:
        return Result(PASS, "tool call received over the stream (%s)" % fraction(ok, SAMPLES))
    if ok == 0:
        return Result(FAIL, "NO tool call over streaming (%s)" % fraction(ok, SAMPLES), data={"attempts": attempts})
    return Result(WARN, "intermittent streamed tool calls (%s)" % fraction(ok, SAMPLES), data={"attempts": attempts})


@check("Parameterless tool over streaming", category="tools", critical=True,
       why="A tool with empty parameters {} breaks streamed tool-calling on some stacks (GLM-5.2/Scaleway). "
           "Many Omnis tools are parameterless (list_skills, list_softskills, ...).")
def parameterless_tool_streaming(client):
    # Non-streaming reference: does it work at all without streaming?
    ns = client.chat(messages=DISCOVER_MESSAGES, tools=[discover_tool()], tool_choice="auto", stream=False)
    ns_ok = ns.ok and "discover_capabilities" in ns.tool_call_names

    ok = 0
    attempts = []
    for _ in range(SAMPLES):
        r = client.chat(messages=DISCOVER_MESSAGES, tools=[discover_tool()], tool_choice="auto", stream=True)
        if r.error:
            return Result(FAIL, "stream errored: %s" % r.error[:200])
        good = r.saw_tool_call_delta and "discover_capabilities" in r.tool_call_names
        ok += 1 if good else 0
        attempts.append({"finish_reason": r.finish_reason, "tool_calls": r.tool_call_names})

    if ok == SAMPLES:
        return Result(PASS, "parameterless tool streams correctly (%s)" % fraction(ok, SAMPLES))
    if ok == 0 and ns_ok:
        return Result(FAIL,
                      "parameterless tool LOST in streaming (%s) but works non-streaming "
                      "→ set disable_streaming for this model in Omnis" % fraction(ok, SAMPLES),
                      data={"stream_attempts": attempts, "nonstream_tool_calls": ns.tool_call_names})
    if ok == 0:
        return Result(FAIL, "parameterless tool not called (%s); non-streaming tool_calls=%s"
                      % (fraction(ok, SAMPLES), ns.tool_call_names), data={"attempts": attempts})
    return Result(WARN, "intermittent parameterless streaming (%s)" % fraction(ok, SAMPLES), data={"attempts": attempts})


@check("Tool result round-trip", category="tools", critical=True,
       why="Omnis loops: model calls a tool, host returns the result as a role:tool message, model continues.")
def tool_result_roundtrip(client):
    tools = [weather_tool()]
    msgs = list(WEATHER_MESSAGES)
    r1 = client.chat(messages=msgs, tools=tools, tool_choice="auto", stream=False)
    if not r1.ok:
        return Result(FAIL, "first call failed: %s" % (r1.error or r1.status_code))
    if not r1.tool_calls:
        return Result(FAIL, "model did not call the tool (finish_reason=%s)" % r1.finish_reason)
    tc = r1.tool_calls[0]
    call_id = tc["id"] or "call_1"
    msgs = msgs + [
        {"role": "assistant", "content": r1.text or None,
         "tool_calls": [{"id": call_id, "type": "function",
                         "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"}}]},
        {"role": "tool", "tool_call_id": call_id,
         "content": '{"city":"Paris","temp_c":21,"condition":"sunny"}'},
    ]
    r2 = client.chat(messages=msgs, tools=tools, stream=False)
    if not r2.ok:
        return Result(FAIL, "follow-up rejected (status=%s): %s" % (r2.status_code, (r2.error or "")[:300]))
    if "21" in r2.text or "sun" in r2.text.lower():
        return Result(PASS, "model consumed the tool result and answered")
    return Result(WARN, "round-trip accepted but answer didn't reference the result", data={"answer": r2.text[:200]})


@check("Parallel tool calls", category="tools", critical=False,
       why="Side info: can the model emit multiple tool_calls in one turn? Useful for fan-out flows.")
def parallel_tool_calls(client):
    r = client.chat(messages=[
        {"role": "user", "content": "Get the weather for BOTH Paris and Tokyo. "
                                    "Call get_weather once per city, in a single response."},
    ], tools=[weather_tool()], tool_choice="auto", stream=False)
    if not r.ok:
        return Result(WARN, "call failed: %s" % (r.error or r.status_code))
    n = len(r.tool_calls)
    if n >= 2:
        return Result(INFO, "emitted %d tool calls in one turn (parallel supported)" % n)
    return Result(INFO, "emitted %d tool call(s); parallel tool calls not observed" % n)


@check("tool_choice=required", category="tools", critical=False,
       why="Side info: forcing a tool call (Omnis router / weak tool-callers) via tool_choice:required.")
def tool_choice_required(client):
    r = client.chat(messages=[{"role": "user", "content": "Say hello."}],
                    tools=[weather_tool()], tool_choice="required", stream=False)
    if not r.ok:
        return Result(WARN, "endpoint rejected tool_choice=required (status=%s)" % r.status_code,
                      data={"error": (r.error or "")[:300]})
    if r.tool_calls:
        return Result(INFO, "tool_choice=required forces a tool call")
    return Result(WARN, "tool_choice=required accepted but no tool call emitted")
