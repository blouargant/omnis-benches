"""Prompt-cache side information.

Omnis can mark a long-lived prefix cacheable (models.json `prompt_cache`) for an
Anthropic-backed LiteLLM gateway, and reads cache hits from
usage.prompt_tokens_details.cached_tokens (or prompt_cache_hit_tokens). This
check reports whether the endpoint surfaces a cache hit at all — it is INFO, not
pass/fail, because caching is provider-specific and optional.
"""

from core import check, Result, INFO, WARN

# A long, stable prefix so a second identical request can hit the cache.
_PREFIX = ("You are a meticulous assistant. " * 400).strip()


@check("Prompt caching", category="caching", critical=False,
       why="Omnis reports cache hit-rate and can enable prompt_cache; this detects whether the endpoint caches.")
def prompt_caching(client):
    msgs = [
        {"role": "system", "content": _PREFIX},
        {"role": "user", "content": "Reply with exactly: OK"},
    ]
    r1 = client.chat(messages=msgs, stream=False)
    if not r1.ok:
        return Result(WARN, "warm-up call failed: %s" % (r1.error or r1.status_code))
    r2 = client.chat(messages=msgs, stream=False)
    if not r2.ok:
        return Result(WARN, "second call failed: %s" % (r2.error or r2.status_code))

    has_details = isinstance((r2.usage or {}).get("prompt_tokens_details"), dict) \
        or "prompt_cache_hit_tokens" in (r2.usage or {})
    cached = r2.cached_tokens
    if cached > 0:
        return Result(INFO, "caching ACTIVE: %d cached prompt tokens on the repeat request" % cached,
                      data={"usage": r2.usage})
    if has_details:
        return Result(INFO, "endpoint exposes cache fields but reported 0 cached tokens "
                            "(may need explicit cache_control / larger prefix)", data={"usage": r2.usage})
    return Result(INFO, "no prompt-cache accounting exposed by this endpoint", data={"usage": r2.usage})
