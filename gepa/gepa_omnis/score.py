"""Task scores from squad-bench records, and the feedback the reflection model reads.

The feedback names what failed (gate names, fact ids) but never the fact match
patterns, the forbidden patterns or the scripted sub-agent replies: those would
let the reflection model write the bench into the prompt.
"""

GATES = ("correct", "quality_gate", "fake_gate")
ANSWER_CHARS = 1500
REQUEST_CHARS = 300


class InfraError(Exception):
    """Every record of a task failed for a reason that is not the agent's."""


def is_infra(rec):
    return bool(rec.get("fake_error")) or rec.get("status") == "error"


def passed(rec):
    gates = [rec.get(g) for g in GATES if rec.get(g) is not None]
    if not gates:
        raise ValueError(f"task {rec.get('task')!r} has no gate: it cannot be scored")
    return rec.get("status") == "done" and all(gates)


def task_score(recs):
    real = [r for r in recs if not is_infra(r)]
    if not real:
        raise InfraError(f"all {len(recs)} records are infrastructure failures")
    return sum(passed(r) for r in real) / len(real)


def _prompts(task):
    if task.get("prompts"):
        return list(task["prompts"])
    return [task.get("prompt", "")]


def feedback(item, recs):
    lines = [f"Agent under test: {item.agent}", "Task given by the user:"]
    lines += [f"> {p}" for p in _prompts(item.task)]
    for i, r in enumerate(recs, 1):
        if is_infra(r):
            continue
        if passed(r):
            lines.append(f"Run {i}: PASSED.")
            continue
        why = []
        if r.get("status") != "done":
            why.append(f"the turn ended with status '{r.get('status')}'")
        missing = (r.get("facts") or {}).get("missing") or []
        if missing:
            why.append("the answer lacks required point(s): " + ", ".join(missing))
        if r.get("forbidden_hits"):
            why.append(f"the answer asserts {len(r['forbidden_hits'])} thing(s) it must not")
        if r.get("fake_failed"):
            why.append("sub-agent use check(s) failed: " + ", ".join(r["fake_failed"]))
        if r.get("correct") is False:
            why.append("the answer is not the expected one")
        lines.append(f"Run {i}: FAILED — " + "; ".join(why or ["a gate failed"]) + ".")
        reqs = (r.get("fake") or {}).get("requests") or []
        if reqs:
            lines.append("  Requests the agent sent to its sub-agents:")
            lines += [f"  - {q.get('agent')}: {(q.get('request') or '')[:REQUEST_CHARS]}" for q in reqs]
        ans = (r.get("answer") or "").strip()
        lines.append("  Final answer: " + (ans[:ANSWER_CHARS] if ans else "(empty)"))
        lines.append(f"  Cost: ${r.get('total_cost_usd', 0)}")
    return "\n".join(lines)
