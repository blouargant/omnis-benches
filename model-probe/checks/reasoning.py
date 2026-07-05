"""Reasoning / thinking-model side information.

Thinking models (GLM, DeepSeek-R1, o1-style) return a `reasoning_content` field.
Omnis does not surface it, but whether it exists — and crucially whether it
*streams* — is diagnostic: GLM-5.2 on Scaleway emits reasoning non-streamed but
drops it (and the tool call) when streamed.
"""

from core import check, Result, INFO, WARN

_PUZZLE = ("Think step by step, then give the final answer: a bat and a ball cost $1.10 in total, "
           "and the bat costs $1.00 more than the ball. How much does the ball cost?")


@check("Reasoning content (thinking model)", category="reasoning", critical=False,
       why="Detects thinking models and whether reasoning streams — the GLM-5.2 streaming fault signature.")
def reasoning_content(client):
    ns = client.chat(messages=[{"role": "user", "content": _PUZZLE}], stream=False)
    if not ns.ok:
        return Result(WARN, "non-stream call failed: %s" % (ns.error or ns.status_code))
    st = client.chat(messages=[{"role": "user", "content": _PUZZLE}], stream=True)

    has_ns = bool(ns.reasoning)
    has_st = bool(st.reasoning)
    if has_ns and has_st:
        return Result(INFO, "thinking model: reasoning_content present (non-stream %dch, streamed %dch)"
                      % (len(ns.reasoning), len(st.reasoning)))
    if has_ns and not has_st:
        return Result(WARN, "reasoning_content present non-streamed (%dch) but NOT in the stream — "
                            "thinking model whose stream drops reasoning (cf. GLM-5.2)" % len(ns.reasoning),
                      data={"stream_finish_reason": st.finish_reason})
    return Result(INFO, "no reasoning_content field (not a thinking model, or hidden by the gateway)")
