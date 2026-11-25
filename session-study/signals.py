"""Cheap signs, read from one recorded turn, that it may have gone wrong."""
import collections
import math
import re

import sessions

_ERROR = re.compile(r"^(Error|error)(:|\s+\S)")
# The notices omnis writes into a tool result (core/permissions, agent/hooks_plugin.go,
# agent/budget_plugin.go, agent/call_cap.go, agent/resumable_agent_tool.go).
_BLOCKED = ("[BLOCKED BY HOOK]", "[BLOCKED BY AUTO MODE]", "[DENIED]")
_HALTED = ("[BUDGET REACHED]", "[TOOL BUDGET REACHED]", "[CALL BUDGET REACHED]")
_EMPTY_SUBAGENT = "stopped without writing a result"
_PUSHBACK = re.compile(
    r"^\s*(non\b|no\b|pas\s|ce n'est pas|c'est faux|faux\b|tu te trompes|wrong\b|incorrect\b|"
    r"that's not|toujours pas|[çc]a ne marche|still not|doesn't work)", re.I)


def p90(counts):
    """90th percentile, nearest rank."""
    if not counts:
        return 0.0
    ordered = sorted(counts)
    return float(ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)])


def for_turn(turn, next_user_text, p90_calls):
    """Signal names for one turn, in the order of the spec's table."""
    found = set()
    seen = collections.Counter()
    n = 0
    for call, _ in sessions.walk(turn.get("tools")):
        n += 1
        result = call.get("result")
        text = sessions.text_of(result)
        if isinstance(result, dict) and result.get("error") or call.get("error"):
            found.add("tool_error")
        if any(_ERROR.match(s.lstrip()) for s in sessions.strings_of(result)):
            found.add("tool_error")
        if any(tag in text for tag in _BLOCKED):
            found.add("blocked")
        if any(tag in text for tag in _HALTED):
            found.add("halted")
        if _EMPTY_SUBAGENT in text:
            found.add("empty_subagent")
        seen[(call.get("name"), sessions.text_of(call.get("args")))] += 1
    if seen and max(seen.values()) >= 3:
        found.add("repeated_call")
    if n > p90_calls:
        found.add("many_calls")
    reply = turn.get("assistant_text") or ""
    if "[Reply cut" in reply:
        found.add("reply_cut")
    if not reply.strip():
        found.add("empty_reply")
    if _PUSHBACK.match(next_user_text or ""):
        found.add("user_pushback")
    order = ["tool_error", "blocked", "halted", "empty_subagent", "repeated_call",
             "many_calls", "reply_cut", "empty_reply", "user_pushback"]
    return [s for s in order if s in found]
