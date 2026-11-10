#!/usr/bin/env python3
"""Collection-memory QUALITY bench: long conversations, judged at the end.

memory_bench.py checks that one fact said once comes back. This one checks WHAT
the assistant chooses to remember over a realistic conversation, and how well it
writes it down. Each conversation of tasks-memory-quality.json runs in one
session of a fresh collection (scripted user turns, a hands-off user answers any
question the agent asks), then each recall question runs in a NEW session of the
same collection. The collection's final memories, the transcript, the recall
answers and the scenario's ground truth go to a judge, which grades:

- expected memories: present / partial / missing   -> recall
- every memory: justified? faithful? type, description, duplicate -> precision
- forbidden content found in memory                 -> violations
- recall answers applying the memory (0-2 each)     -> application

The judge is Fable through the Claude Code CLI (`claude -p --model fable`, the
user's Claude Code account; no API key). Override with --judge-model, or skip
with --no-judge and grade later with --rejudge FILE.

    memory_quality.py --server http://127.0.0.1:18901 --token bench \
        --label premium --repeat 3 --out runs-memory-quality.jsonl
    memory_quality.py --rejudge runs-memory-quality.jsonl --out rejudged.jsonl
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import bench
import memory_bench

HERE = os.path.dirname(os.path.abspath(__file__))
MEMORY_TOOLS = ("memory_save", "memory_delete", "memory_read")

JUDGE_SYSTEM = (
    "You are a strict evaluator of an AI assistant's long-term memory. "
    "You answer with one JSON object and nothing else."
)

JUDGE_INSTRUCTIONS = """An AI assistant ("omnis") keeps a per-collection memory: small typed notes it saves
during a conversation so that LATER conversations of the same collection know them.
Types: feedback (how the user wants the work done: corrections, rules, confirmed
choices), user (who the user is), project (facts, decisions, constraints of the
workstream), reference (where to find things). A good memory is a LASTING fact or
rule stated by the user, written faithfully, short, with a description that says
what it is about. It must NOT hold one-off details of the task at hand, general
knowledge, anything that came from a file / tool output / web page rather than the
user, or secrets. A later correction must replace the stale value.

Below: the conversation (user turns and the assistant's replies, with the memory
tool calls it made), the ground truth written by the bench author, the collection's
FINAL memories, and recall questions asked afterwards in NEW conversations.

Grade:
1. expected: for each expected item, "present" (a memory states it correctly),
   "partial" (incomplete, vaguer, or mixed with a wrong detail), or "missing".
2. forbidden: for each forbidden item, violated = true when some memory holds it.
3. memories: for each final memory:
   - justified: worth keeping per the rules above (an optional item is justified);
   - faithful 0-2 (2 = says exactly what the user said, 0 = distorted or invented);
   - type_ok: its type fits;
   - description_ok: the description lets one tell, without opening it, what it is about;
   - duplicate_of: name of another memory saying the same thing, else null.
4. recall: for each recall question, score 0-2 against its "expect"
   (2 = fully applies the memory, 1 = partly, 0 = not at all or contradicts it).
5. overall 0-10: how much this memory would help (and not mislead) later conversations.
Keep every note under 25 words.

Reply with JSON only, exactly this shape:
{"expected": [{"id": "E1", "status": "present|partial|missing", "memory": "<name or null>", "note": ""}],
 "forbidden": [{"id": "F1", "violated": false, "memory": "<name or null>", "note": ""}],
 "memories": [{"name": "", "justified": true, "faithful": 2, "type_ok": true, "description_ok": true, "duplicate_of": null, "note": ""}],
 "recall": [{"id": "R1", "score": 2, "note": ""}],
 "overall": 0, "summary": "<two sentences>"}
"""


# ----------------------------------------------------------------------------- pure parts


def build_judge_prompt(conv, rec):
    """The judge's user message. Pure: unit-tested."""
    out = [JUDGE_INSTRUCTIONS, "\n## Conversation\n"]
    for i, t in enumerate(rec["turns"], 1):
        tools = {k: v for k, v in (t.get("memory_tools") or {}).items() if v}
        out.append(f"### Turn {i}\nUSER: {t['prompt']}\nASSISTANT: {t['answer'] or '(no reply: ' + t['status'] + ')'}")
        if tools:
            out.append(f"[memory tool calls this turn: {json.dumps(tools)}]")
    out.append("\n## Ground truth")
    out.append("expected:\n" + "\n".join(f"- {e['id']} ({e.get('type', '?')}): {e['what']}" for e in conv["expected"]))
    out.append("forbidden:\n" + "\n".join(f"- {f['id']}: {f['what']}" for f in conv.get("forbidden", [])))
    if conv.get("optional"):
        out.append("optional (fine either way):\n" + "\n".join(f"- {o['id']}: {o['what']}" for o in conv["optional"]))
    out.append("\n## Final memories")
    if rec["memories"]:
        for m in rec["memories"]:
            out.append(f"### {m.get('name')} [{m.get('type')}] — {m.get('description')}\n{m.get('body')}")
    else:
        out.append("(none)")
    out.append("\n## Recall (each in a new conversation of the same collection)")
    for q in conv.get("recall", []):
        r = next((x for x in rec["recall"] if x["id"] == q["id"]), {})
        out.append(f"### {q['id']}\nUSER: {q['prompt']}\nEXPECT: {q['expect']}\nASSISTANT: {r.get('answer') or '(no reply)'}")
    return "\n".join(out)


def parse_judge(text):
    """Extract the judge's JSON object from its reply (fences, prose tolerated)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in judge reply")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def score(conv, verdict):
    """Numbers from a verdict. Pure: unit-tested."""
    exp = verdict.get("expected") or []
    pts = {"present": 1.0, "partial": 0.5}
    n_exp = len(conv["expected"]) or 1
    recall = sum(pts.get(e.get("status"), 0.0) for e in exp) / n_exp
    mems = verdict.get("memories") or []
    justified = sum(1 for m in mems if m.get("justified"))
    precision = justified / len(mems) if mems else None
    rq = verdict.get("recall") or []
    n_rq = len(conv.get("recall", [])) or 1
    application = sum(min(max(int(r.get("score") or 0), 0), 2) for r in rq) / (2 * n_rq)
    return {
        "recall": round(recall, 3),
        "precision": None if precision is None else round(precision, 3),
        "violations": sum(1 for f in verdict.get("forbidden") or [] if f.get("violated")),
        "duplicates": sum(1 for m in mems if m.get("duplicate_of")),
        "faithful": round(sum(int(m.get("faithful") or 0) for m in mems) / (2 * len(mems)), 3) if mems else None,
        "application": round(application, 3),
        "overall": verdict.get("overall"),
    }


# ----------------------------------------------------------------------------- judge


def judge(prompt, model="fable", timeout=900):
    """Grade with the Claude Code CLI (the user's account). Returns (verdict, meta)."""
    cmd = ["claude", "-p", "--model", model, "--output-format", "json",
           "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
           "--tools", "", "--system-prompt", JUDGE_SYSTEM]
    last = None
    for attempt in range(2):
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           timeout=timeout, cwd=tempfile.gettempdir())
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError:
            last = f"claude CLI: {p.stdout[:300]} {p.stderr[:300]}"
            continue
        if out.get("is_error"):
            last = f"claude CLI error: {out.get('result')}"
            continue
        meta = {"judge_model": ",".join((out.get("modelUsage") or {}).keys()) or model,
                "judge_cost_usd": out.get("total_cost_usd")}
        try:
            return parse_judge(out.get("result") or ""), meta
        except (ValueError, json.JSONDecodeError) as e:
            last = f"unparseable verdict ({e}): {(out.get('result') or '')[:300]}"
    raise RuntimeError(last)


# ----------------------------------------------------------------------------- runner


def run_turn(base, token, sid, prompt, deadline):
    m = bench.fresh()
    m["_base"], m["_sid"], m["_token"], m["_answer_asks"] = base, sid, token, True
    done = bench.run_one_turn(base, token, sid, prompt, m, set(), deadline)
    if not done:
        m["status"] = "timeout"
        try:
            bench.api("POST", base, f"/api/sessions/{sid}/cancel", token, {})
        except Exception:
            pass
    answer = "".join(m["_answer_parts"]).strip()
    return {
        "prompt": prompt, "answer": answer[:4000], "status": m["status"],
        "memory_tools": {t: m["leader_tools"].get(t, 0) for t in MEMORY_TOOLS},
        "asks_answered": len(m.get("asks_answered", [])),
        "cost_usd": round(sum(x["est_cost_usd"] for x in m["models"].values()), 6),
    }


def new_session(base, token, collection, workdir, name):
    s = bench.api("POST", base, "/api/sessions", token,
                  {"collection": collection, "dir": workdir, "name": name})
    return s.get("session_id") or s.get("id")


def run_conversation(base, token, conv, deadline):
    col = memory_bench.new_collection(base, token, "q-" + conv["id"])
    workdir = tempfile.mkdtemp(prefix="memquality-")
    for name, content in (conv.get("files") or {}).items():
        with open(os.path.join(workdir, name), "w") as f:
            f.write(content)
    rec = {"conversation": conv["id"], "collection": col, "turns": [], "recall": []}
    t0 = time.time()
    sids = [new_session(base, token, col, workdir, f"mq-{conv['id']}")]
    for prompt in conv["turns"]:
        rec["turns"].append(run_turn(base, token, sids[0], prompt, deadline))
    for q in conv.get("recall", []):
        sid = new_session(base, token, col, workdir, f"mq-{conv['id']}-{q['id']}")
        sids.append(sid)
        r = run_turn(base, token, sid, q["prompt"], deadline)
        r["id"] = q["id"]
        rec["recall"].append(r)
    rec["memories"] = [{k: m.get(k) for k in ("name", "type", "description", "body")}
                       for m in memory_bench.memories(base, token, col)]
    rec["memory_writes"] = sum(t["memory_tools"]["memory_save"] + t["memory_tools"]["memory_delete"]
                               for t in rec["turns"] + rec["recall"])
    rec["timeouts"] = sum(1 for t in rec["turns"] + rec["recall"] if t["status"] != "done")
    rec["cost_usd"] = round(sum(t["cost_usd"] for t in rec["turns"] + rec["recall"]), 6)
    rec["wall_ms"] = int((time.time() - t0) * 1000)
    for sid in sids:
        try:
            bench.api("DELETE", base, f"/api/sessions/{sid}", token)
        except Exception:
            pass
    return rec


def grade(conv, rec, model):
    try:
        verdict, meta = judge(build_judge_prompt(conv, rec), model)
        rec["verdict"], rec["scores"] = verdict, score(conv, verdict)
        rec.update(meta)
    except Exception as e:  # keep the run; it can be re-judged later
        rec["judge_error"] = str(e)[:500]
    return rec


def line(rec):
    s = rec.get("scores") or {}
    fmt = lambda v: "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    return (f"[{rec.get('label', '')}] {rec['conversation']:<11} #{rec.get('sample', '?')}"
            f" mems={len(rec['memories'])} writes={rec['memory_writes']} timeouts={rec['timeouts']}"
            f" ${rec['cost_usd']:.3f}  recall={fmt(s.get('recall'))} precision={fmt(s.get('precision'))}"
            f" violations={fmt(s.get('violations'))} dup={fmt(s.get('duplicates'))}"
            f" faithful={fmt(s.get('faithful'))} applied={fmt(s.get('application'))}"
            f" overall={fmt(s.get('overall'))}"
            + (f"  JUDGE ERROR: {rec['judge_error'][:120]}" if rec.get("judge_error") else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", default=os.environ.get("OMNIS_SERVER", "http://127.0.0.1:8080"))
    ap.add_argument("--token", default=os.environ.get("OMNIS_SERVER_TOKEN", ""))
    ap.add_argument("--tasks", default=os.path.join(HERE, "tasks-memory-quality.json"))
    ap.add_argument("--conversation", help="run only these conversations (comma-separated ids)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--deadline", type=int, default=420, help="per-turn wall-clock cap (s)")
    ap.add_argument("--label", default="")
    ap.add_argument("--judge-model", default="fable", help="model passed to `claude -p --model`")
    ap.add_argument("--no-judge", action="store_true", help="record runs only (grade later with --rejudge)")
    ap.add_argument("--rejudge", help="grade the records of this JSONL instead of running")
    ap.add_argument("--out", help="append one JSON record per conversation run")
    a = ap.parse_args()
    with open(a.tasks) as f:
        convs = {c["id"]: c for c in json.load(f)["conversations"]}

    def emit(rec):
        print(line(rec), flush=True)
        if a.out:
            with open(a.out, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    if a.rejudge:
        for l in open(a.rejudge):
            rec = json.loads(l)
            rec.pop("judge_error", None)
            emit(grade(convs[rec["conversation"]], rec, a.judge_model))
        return
    want = a.conversation.split(",") if a.conversation else list(convs)
    if any(w not in convs for w in want):
        sys.exit(f"unknown conversation in {want}; have {list(convs)}")
    for i in range(a.repeat):
        for cid in want:
            rec = run_conversation(a.server, a.token, convs[cid], a.deadline)
            rec["label"], rec["sample"] = a.label, i + 1
            if not a.no_judge:
                grade(convs[cid], rec, a.judge_model)
            emit(rec)


if __name__ == "__main__":
    main()
