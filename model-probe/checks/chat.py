"""Baseline chat-completion checks."""

from core import check, Result, PASS, FAIL, WARN, fmt_ms


@check("Basic chat completion", category="chat", critical=True,
       why="Baseline: the OpenAI-compatible /chat/completions endpoint answers at all.")
def basic_completion(client):
    r = client.chat(messages=[{"role": "user", "content": "Reply with exactly: OK"}], stream=False)
    if not r.ok:
        return Result(FAIL, "request failed (status=%s): %s" % (r.status_code, (r.error or "")[:300]))
    if r.text.strip():
        return Result(PASS, "responded in %s (%d chars)" % (fmt_ms(r.elapsed), len(r.text)),
                      data={"finish_reason": r.finish_reason})
    return Result(FAIL, "empty response body", data={"raw": str(r.raw)[:300]})


@check("Streaming chat completion", category="chat", critical=True,
       why="Omnis streams tokens to the UI; the endpoint must emit SSE content deltas.")
def streaming_completion(client):
    r = client.chat(messages=[{"role": "user", "content": "Count from 1 to 5, one number per line."}], stream=True)
    if r.error:
        return Result(FAIL, "stream errored (status=%s): %s" % (r.status_code, r.error[:300]))
    if r.saw_text_delta and r.n_chunks > 1:
        return Result(PASS, "%d SSE chunks, first token in %s" % (r.n_chunks, fmt_ms(r.ttft)),
                      data={"finish_reason": r.finish_reason})
    if r.text:
        return Result(WARN, "got text but only %d chunk(s) — endpoint may not truly stream" % r.n_chunks,
                      data={"chunks": r.n_chunks})
    return Result(FAIL, "no streamed text", data={"chunks": r.n_chunks, "finish_reason": r.finish_reason})


@check("System instruction adherence", category="chat", critical=False,
       why="Omnis shapes every agent via a system instruction; the model must honor it.")
def system_instruction(client):
    r = client.chat(messages=[
        {"role": "system", "content": "You always answer with exactly one word: PONG. Nothing else."},
        {"role": "user", "content": "ping"},
    ], stream=False)
    if not r.ok:
        return Result(FAIL, "failed: %s" % (r.error or r.status_code))
    if "pong" in r.text.lower():
        return Result(PASS, "system instruction honored")
    return Result(WARN, "system instruction weakly followed", data={"answer": r.text[:120]})
