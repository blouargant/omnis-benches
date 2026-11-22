#!/usr/bin/env python3
"""Deterministic answer scoring for squad-bench — layer 1 of the quality gate.

Pure functions, no I/O. This module decides which cost variant is allowed to
ship, so a bug here would silently ratify a degraded variant: it is the one
part of the harness that is unit-tested.

A task declares:
    facts:     [{id, on?, required, match}]   `on` = turn index; absent = any turn
    forbidden: [{id, on?, match, unless?}]    `unless` = an acceptable hedge

`match` and `unless` use bench.py's existing convention: `/regex/` (case
insensitive) or a plain case-insensitive substring.
"""
import difflib
import re


def match_rule(pattern, text):
    """True if `pattern` matches `text`. `/regex/` or case-insensitive substring."""
    if not pattern:
        return False
    text = text or ""
    if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 1:
        return bool(re.search(pattern[1:-1], text, re.I))
    return pattern.lower() in text.lower()


def _answer_for(answers, idx):
    """The answer a rule applies to: one turn when `on` is set, else all of them."""
    answers = answers or []
    if idx is None:
        return "\n".join(answers)
    return answers[idx] if 0 <= idx < len(answers) else ""


def score_facts(facts, answers):
    found, missing, optional_found = [], [], []
    required = 0
    for f in facts or []:
        hit = match_rule(f.get("match"), _answer_for(answers, f.get("on")))
        if f.get("required"):
            required += 1
            (found if hit else missing).append(f.get("id"))
        elif hit:
            optional_found.append(f.get("id"))
    return {"found": found, "missing": missing,
            "required": required, "optional_found": optional_found}


def check_forbidden(forbidden, answers):
    """Ids of violated rules. A match that carries its `unless` hedge is NOT a
    violation — the baseline names an unconfirmed part reference while saying so,
    and that is correct behaviour, not a defect.

    When a rule specifies `on` (explicit turn index), only that turn is evaluated.
    When `on` is absent (None), each turn is evaluated individually — a violation is
    any single turn that matches `match` without also matching `unless` in that same
    turn. This ensures the hedge must accompany the assertion; a hedge in a distant
    turn does not whitewash an unhedged assertion elsewhere."""
    hits = []
    for f in forbidden or []:
        on_idx = f.get("on")

        if on_idx is not None:
            # Explicit turn: check only that turn (original behavior)
            text = _answer_for(answers, on_idx)
            if not match_rule(f.get("match"), text):
                continue
            if f.get("unless") and match_rule(f["unless"], text):
                continue
            hits.append(f.get("id"))
        else:
            # No explicit turn: check each turn individually
            # A violation is any turn that matches `match` but not `unless`
            answers_list = answers or []
            violated = False
            for turn_text in answers_list:
                if not match_rule(f.get("match"), turn_text):
                    continue
                # Turn matches `match` - check if it also has the `unless` hedge
                if f.get("unless") and match_rule(f["unless"], turn_text):
                    # Has the hedge - not a violation in this turn
                    continue
                # No hedge in this turn - violation found
                violated = True
                break

            if violated:
                hits.append(f.get("id"))
    return hits


def quality_gate(task, answers):
    """Layer-1 verdict. `quality_gate` is None when the task declares no rules."""
    facts = score_facts(task.get("facts"), answers)
    hits = check_forbidden(task.get("forbidden"), answers)
    declared = bool(task.get("facts")) or bool(task.get("forbidden"))
    passed = (not facts["missing"] and not hits) if declared else None
    return {"facts": facts, "forbidden_hits": hits, "quality_gate": passed}


# ----------------------------------------------------------------------------- fake sub-agents
FAKE_REQUEST_CHARS = 500
NEAR_RATIO = 0.9      # two requests at least this similar are the same request reworded
_FAKE_AGENT_KEYS = ("min_calls", "max_calls", "min_distinct", "max_repeats", "max_near_repeats")


def normalise_request(text):
    return " ".join((text or "").lower().split())


def similar(a, b):
    """True when two requests are the same or nearly so (case and spacing
    ignored): a model rarely repeats itself byte for byte, so "please" or
    "try again" added to a request does not make it a new one."""
    a, b = normalise_request(a), normalise_request(b)
    return a == b or difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= NEAR_RATIO


def _max_parallel(calls):
    """Largest number of calls open at once. A call ending when another starts
    does not overlap it; a call with no end is open from its start on."""
    events = []
    for c in calls:
        events.append((c.get("started_ms") or 0, 1))
        if c.get("ended_ms") is not None:
            events.append((c["ended_ms"], -1))
    best = cur = 0
    for _, step in sorted(events):      # at one instant, -1 sorts before +1
        cur += step
        best = max(best, cur)
    return best


def fake_summary(calls):
    """Reduce a fake_subagents call log to what a leader did with each sub-agent."""
    count, distinct, earlier, near = {}, {}, {}, {}
    for c in calls or []:
        a = c.get("agent") or "?"
        req = normalise_request(c.get("request"))
        count[a] = count.get(a, 0) + 1
        distinct.setdefault(a, set()).add(req)
        near[a] = near.get(a, 0) + any(similar(req, e) for e in earlier.get(a, []))
        earlier.setdefault(a, []).append(req)
    return {
        "calls": count,
        "distinct_requests": {a: len(s) for a, s in distinct.items()},
        "repeats": {a: count[a] - len(distinct[a]) for a in count},
        "near_repeats": near,
        "max_parallel": _max_parallel(calls or []),
        "requests": [{"agent": c.get("agent"), "n": c.get("n"),
                      "request": (c.get("request") or "")[:FAKE_REQUEST_CHARS]} for c in calls or []],
    }


def check_fake(expect, summary):
    """Verdict of a task's `expect_fake` on a fake_summary. `fake_gate` is None
    when the task expects nothing; a failed check is named `<agent>.<key>` or
    `min_parallel`. An agent that was never called counts as 0."""
    if not expect:
        return {"fake_gate": None, "fake_failed": []}
    failed = []
    for agent, want in (expect.get("agents") or {}).items():
        got = {"calls": summary["calls"].get(agent, 0),
               "distinct": summary["distinct_requests"].get(agent, 0),
               "repeats": summary["repeats"].get(agent, 0),
               "near_repeats": summary.get("near_repeats", {}).get(agent, 0)}
        for key in _FAKE_AGENT_KEYS:
            if key not in want:
                continue
            bound, field = key.split("_", 1)
            ok = got[field] >= want[key] if bound == "min" else got[field] <= want[key]
            if not ok:
                failed.append(f"{agent}.{key}")
    if "min_parallel" in expect and summary["max_parallel"] < expect["min_parallel"]:
        failed.append("min_parallel")
    return {"fake_gate": not failed, "fake_failed": failed}
