#!/usr/bin/env python3
"""Collection-memory bench: does a correction said once stick?

Drives a running omnis-server (one with collection memory: the memory_save /
memory_read / memory_delete tools and GET /api/collections/:name/memories).
Each scenario of tasks-memory.json runs in a FRESH collection: its steps are
prompts sent to sessions of that collection (a step naming another session id
gets a new session; collection "other" is a second fresh collection, to check
memory does not leak). After the last step the collection's memories are read
back and the scenario's checks run. One JSON record per scenario run.

    memory_bench.py --server http://127.0.0.1:18901 --token bench --repeat 3 \
        --label premium --out runs-memory.jsonl

Stdlib only; reuses bench.py's HTTP/SSE plumbing and cost accounting.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import uuid
from urllib.parse import quote

import bench

HERE = os.path.dirname(os.path.abspath(__file__))
MEMORY_WRITE_TOOLS = ("memory_save", "memory_delete")


def new_collection(base, token, tag):
    name = f"mb-{tag}-{uuid.uuid4().hex[:6]}"
    bench.api("POST", base, "/api/collections", token, {"name": name})
    return name


def memories(base, token, collection):
    out = bench.api("GET", base, f"/api/collections/{quote(collection)}/memories", token)
    return out.get("memories") or []


def run_step(base, token, sid, prompt, deadline):
    m = bench.fresh()
    m["_base"], m["_sid"], m["_token"] = base, sid, token
    done = bench.run_one_turn(base, token, sid, prompt, m, set(), deadline)
    answer = "".join(m["_answer_parts"]).strip()
    if not done and m["status"] != "ask_user":
        m["status"] = "timeout"
        try:
            bench.api("POST", base, f"/api/sessions/{sid}/cancel", token, {})
        except Exception:
            pass
    return m, answer


def evaluate(scn, step_answers, mems):
    """Return {check_name: bool}. Pure: unit-tested in test_memory_bench.py."""
    checks = {}
    for i, (step, ans) in enumerate(zip(scn["steps"], step_answers)):
        if step.get("answer_re"):
            checks[f"step{i+1}_answer"] = bool(re.search(step["answer_re"], ans or "", re.I | re.M))
        if step.get("answer_not_re"):
            checks[f"step{i+1}_answer_not"] = not re.search(step["answer_not_re"], ans or "", re.I | re.M)
    texts = [f"{m.get('name','')}\n{m.get('description','')}\n{m.get('body','')}" for m in mems]
    if scn.get("memory_re"):
        checks["memory_saved"] = any(re.search(scn["memory_re"], t, re.I) for t in texts)
    if scn.get("memory_not_re"):
        checks["memory_absent"] = not any(re.search(scn["memory_not_re"], t, re.I) for t in texts)
    if scn.get("memory_not_re_alone"):
        # the stale value may survive only next to the new one ("9443, not 8443")
        alone, new = scn["memory_not_re_alone"], scn.get("memory_re", "$^")
        checks["stale_value_gone"] = not any(re.search(alone, t) and not re.search(new, t) for t in texts)
    if "max_memories" in scn:
        checks["memory_count"] = len(mems) <= scn["max_memories"]
    if scn.get("max_memories_matching"):
        rule = scn["max_memories_matching"]
        n = sum(1 for t in texts if re.search(rule["re"], t, re.I))
        checks["no_duplicate"] = n <= rule["max"]
    return checks


def run_scenario(base, token, scn, deadline, tag):
    cols = {"main": new_collection(base, token, scn["id"])}
    workdir = tempfile.mkdtemp(prefix="membench-")
    sessions, answers, steps_out = {}, [], []
    rec = {"scenario": scn["id"], "collection": cols["main"], "status": "done",
           "cost_usd": 0.0, "memory_writes": 0, "calls": 0}
    t0 = time.time()
    for step in scn["steps"]:
        key = step.get("collection", "main")
        if key not in cols:
            cols[key] = new_collection(base, token, scn["id"] + "-" + key)
        sid = sessions.get(step["session"])
        if sid is None:
            body = {"collection": cols[key], "dir": workdir, "name": f"mb-{scn['id']}-{step['session']}"}
            sess = bench.api("POST", base, "/api/sessions", token, body)
            sid = sessions[step["session"]] = sess.get("session_id") or sess.get("id")
        prompt = step["prompt"] + f"\n\n(run {tag})"  # defeat the gateway response cache
        m, ans = run_step(base, token, sid, prompt, deadline)
        answers.append(ans)
        writes = sum(m["leader_tools"].get(t, 0) for t in MEMORY_WRITE_TOOLS)
        cost = sum(x["est_cost_usd"] for x in m["models"].values())
        rec["memory_writes"] += writes
        rec["cost_usd"] += cost
        rec["calls"] += sum(x["calls"] for x in m["models"].values())
        steps_out.append({"session": step["session"], "status": m["status"],
                          "memory_tools": {t: m["leader_tools"].get(t, 0) for t in MEMORY_WRITE_TOOLS + ("memory_read",)},
                          "cost_usd": round(cost, 6), "answer": ans[:600]})
        if m["status"] != "done":
            rec["status"] = m["status"]
            break
    mems = memories(base, token, cols["main"])
    rec["memories"] = [{k: x.get(k) for k in ("name", "type", "description", "body")} for x in mems]
    rec["checks"] = evaluate(scn, answers + [""] * (len(scn["steps"]) - len(answers)), mems)
    rec["passed"] = rec["status"] == "done" and all(rec["checks"].values())
    rec["steps"] = steps_out
    rec["wall_ms"] = int((time.time() - t0) * 1000)
    rec["cost_usd"] = round(rec["cost_usd"], 6)
    for sid in sessions.values():
        try:
            bench.api("DELETE", base, f"/api/sessions/{sid}", token)
        except Exception:
            pass
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", default=os.environ.get("OMNIS_SERVER", "http://127.0.0.1:8080"))
    ap.add_argument("--token", default=os.environ.get("OMNIS_SERVER_TOKEN", ""))
    ap.add_argument("--tasks", default=os.path.join(HERE, "tasks-memory.json"))
    ap.add_argument("--scenario", help="run one scenario by id")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--deadline", type=int, default=420, help="per-step wall-clock cap (s)")
    ap.add_argument("--label", default="", help="tag stored in every record (e.g. the model tier)")
    ap.add_argument("--out", help="append one JSON record per scenario run")
    args = ap.parse_args()
    with open(args.tasks) as f:
        scns = json.load(f)["scenarios"]
    if args.scenario:
        scns = [s for s in scns if s["id"] == args.scenario] or sys.exit(f"no scenario {args.scenario}")
    for i in range(args.repeat):
        for scn in scns:
            tag = uuid.uuid4().hex[:8]
            rec = run_scenario(args.server, args.token, scn, args.deadline, tag)
            rec["label"], rec["sample"] = args.label, i + 1
            fails = [k for k, v in rec["checks"].items() if not v]
            print(f"[{args.label}] {scn['id']:<13} #{i+1} {'PASS' if rec['passed'] else 'FAIL'}"
                  f" {rec['status']:<8} writes={rec['memory_writes']} mems={len(rec['memories'])}"
                  f" ${rec['cost_usd']:.4f} {rec['wall_ms']/1000:.0f}s"
                  + (f"  failed: {', '.join(fails)}" if fails else ""), flush=True)
            if args.out:
                with open(args.out, "a") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
