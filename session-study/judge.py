"""LLM judges: one for a recorded turn, one for a replayed run."""
import json
import os

import llm

VERDICTS = ("failed", "wasteful", "ok")
OUTLINE_CAP = 40000

TURN_SYSTEM = """You review one recorded turn of an AI agent: the user's request, the tool calls the agent made (one per numbered line, a sub-agent's own calls indented), its reply, and the user's next message if any.
Say whether the turn went wrong. Report only what the transcript shows:
- a tool error or a refusal the agent did not recover from;
- a loop: the same call, or near-identical calls, repeated without progress;
- a reply that does not address the request, is empty, or was cut;
- the user pushing back or repeating the request in the next message;
- effort clearly out of proportion with the request.
Do not fact-check the reply: you cannot verify its claims, so do not guess.
verdict: "failed" (the user did not get what they asked for), "wasteful" (a correct-looking answer reached at a clearly excessive cost), or "ok".
""" + llm.FENCE_RULE + """
Reply with JSON only: {"verdict": "failed|wasteful|ok", "kind": "<label of at most four words, empty when ok>", "reason": "<one sentence>", "calls": [<line numbers that show it>]}"""


def _cap(outline):
    lines = ["%d %s" % (i + 1, l) for i, l in enumerate(outline.splitlines())]
    text = "\n".join(lines)
    if len(text) <= OUTLINE_CAP:
        return text
    head, tail, size = [], [], 0
    i, j = 0, len(lines) - 1
    while i <= j and size + len(lines[i]) + len(lines[j]) < OUTLINE_CAP:
        head.append(lines[i])
        tail.append(lines[j])
        size += len(lines[i]) + len(lines[j]) + 2
        i, j = i + 1, j - 1
    return "\n".join(head + ["… %d lines omitted …" % (j - i + 1)] + tail[::-1])


def turn_prompt(turn):
    body = "REQUEST\n%s\n\nTOOL CALLS\n%s\n\nREPLY\n%s\n\nNEXT USER MESSAGE\n%s" % (
        turn.get("user_text", ""), _cap(turn.get("outline", "")) or "(none)",
        turn.get("reply", "") or "(empty)", turn.get("next_user_text", "") or "(none)")
    return TURN_SYSTEM, llm.fence(body)


def parse_turn(text):
    d = llm.extract_json(text)
    if d.get("verdict") not in VERDICTS:
        raise ValueError("verdict %r is not one of %s" % (d.get("verdict"), "/".join(VERDICTS)))
    calls = d.get("calls")
    return {"verdict": d["verdict"], "kind": str(d.get("kind") or ""), "reason": str(d.get("reason") or ""),
            "calls": calls if isinstance(calls, list) else []}


def _rewrite(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def run_items(items, out_path, key, model, ask, call=llm.call):
    """Judge each item once. A row with "error" is retried on the next run; a
    good row is kept. ask(item) -> (system, user, parse)."""
    done = {}
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    done[row[key]] = row
    summary = {"judged": 0, "errors": 0, "skipped": 0}
    for item in items:
        k = item[key]
        if k in done and "error" not in done[k]:
            summary["skipped"] += 1
            continue
        row = {key: k, "model": model}
        try:
            system, user, parse = ask(item)
            text, usage = call(model, system, user)
            row.update(parse(text))
            row["usage"] = usage
            summary["judged"] += 1
        except Exception as e:  # a bad reply or a gateway error must not stop the run
            row["error"] = "%s: %s" % (type(e).__name__, e)
            summary["errors"] += 1
        done[k] = row
        _rewrite(out_path, done.values())
    return summary


def run_judge(turns, out_path, model, call=llm.call):
    return run_items(turns, out_path, "turn_id", model,
                     lambda t: turn_prompt(t) + (parse_turn,), call=call)


RUN_SYSTEM = """You grade one run of an AI agent on a test scenario. You get the request, a rubric, the agent's answer, and the run's metrics.
- "passed": true when the answer satisfies every statement of the rubric's pass list.
- "failure_seen": true only when the rubric's specific failure happened in this run, as shown by the answer or the metrics. Any other shortcoming is not that failure: answer false. When the rubric names no failure, answer false.
Judge what is shown; do not fact-check beyond the rubric.
""" + llm.FENCE_RULE + """
Reply with JSON only: {"passed": true|false, "failure_seen": true|false, "reason": "<one sentence>"}"""


def run_prompt(scenario, record):
    rubric = scenario.get("rubric") or {}
    prompts = scenario.get("prompts") or [scenario.get("prompt", "")]
    metrics = "tool calls by the leader: %s; by sub-agents: %s; delegations: %s; pages fetched: %s; cost: $%s; seconds: %s" % (
        json.dumps(record.get("leader_tools") or {}), json.dumps(record.get("subagent_tools") or {}),
        json.dumps(record.get("delegations") or {}), record.get("fetches", "?"),
        record.get("total_cost_usd", "?"), round((record.get("wall_ms") or 0) / 1000))
    user = "REQUEST\n%s\n\nRUBRIC — pass when:\n%s\n\nRUBRIC — the specific failure to look for:\n%s\n\nMETRICS\n%s\n\nANSWER\n%s" % (
        "\n---\n".join(prompts), "\n".join("- " + p for p in rubric.get("pass") or []),
        rubric.get("failure") or "(none: control scenario)", metrics,
        llm.fence((record.get("answer") or "")[:30000]))
    return RUN_SYSTEM, user


def parse_run(text):
    d = llm.extract_json(text)
    if not isinstance(d.get("passed"), bool) or not isinstance(d.get("failure_seen"), bool):
        raise ValueError("passed and failure_seen must be true or false")
    return {"passed": d["passed"], "failure_seen": d["failure_seen"], "reason": str(d.get("reason") or "")}
