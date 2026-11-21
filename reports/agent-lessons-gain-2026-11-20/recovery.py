#!/usr/bin/env python3
"""Recovery cost after a trap hit: tool calls between the first Bash result
carrying the trap's error and the first Bash result carrying the task's token,
split by whether that first failing result carried a lesson hint.
  recovery.py <workdir> [<workdir> ...]     (needs the arms' homes)"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
TASKS = {t["id"]: t for t in json.load(open(os.path.join(HERE, "..", "..", "squad-bench", "tasks-lessons-gain.json")))["tasks"]}

def txt(x):
    return x if isinstance(x, str) else json.dumps(x or "")

rows = {}
for W in sys.argv[1:]:
    for l in open(os.path.join(W, "runs.jsonl")):
        r = json.loads(l)
        t = TASKS[r["task"]]
        if not t["marker"]:
            continue
        token = t["check"][0]["answer"].strip("/")
        try:
            conv = json.load(open(f"{W}/{r['arm']}-{r['rep']}/home/logs/conversation_{r['session_id']}.json"))
        except OSError:
            continue
        calls = [c for tu in (conv.get("turns") or []) for c in (tu.get("tools") or [])]
        hit = next((i for i, c in enumerate(calls) if c.get("name") == "Bash" and t["marker"] in txt(c.get("result"))
                    and "#!/bin/sh" not in txt(c.get("result"))), None)
        key = (r["arm"], r["trap_kind"])
        d = rows.setdefault(key, {"no_hit": 0, "hinted": [], "plain": [], "unrecovered": 0})
        if hit is None:
            d["no_hit"] += 1
            continue
        ok = next((i for i, c in enumerate(calls) if i > hit and c.get("name") == "Bash" and token in txt(c.get("result"))), None)
        if ok is None:
            d["unrecovered"] += 1
            continue
        (d["hinted"] if '"lesson"' in txt(calls[hit].get("result")) else d["plain"]).append(ok - hit)

mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")
print("| Arm | Trap kind | Sessions without a hit | Hit, no hint: n / calls to recover | Hit with hint: n / calls to recover | Never recovered |")
print("|---|---|---|---|---|---|")
for (arm, kind), d in sorted(rows.items()):
    print(f"| {arm} | {kind} | {d['no_hit']} | {len(d['plain'])} / {mean(d['plain']):.2f} | {len(d['hinted'])} / {mean(d['hinted']):.2f} | {d['unrecovered']} |")
