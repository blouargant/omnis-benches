#!/usr/bin/env python3
"""Run squad-bench/tasks-lessons.json once against a running omnis-server and
add what bench.py does not measure: root tool errors, lesson hints delivered,
a file/answer check, and the lessons on disk after the run.

Each task runs in a FRESH copy of its fixture (fixtures/<id>), git-seeded, so
a run never sees the previous run's edits. bench.py keeps the session
(--keep) so its conversation file can be read: every tool call of the turn is
recorded there (sessions.ToolCallRecord, root calls and sub-agent children)
with its result, which is what the error counts are taken from.

Usage:
  run_lessons.py --server http://127.0.0.1:18311 --token bench \
      --home <arm>/home --arm on --run 1 --out runs-on.jsonl
  # offline, no model call: re-score with the current tasks file, write
  # results.json and print the report tables (needs each arm's home for the
  # conversation files; records keep their own stats when a file is gone)
  run_lessons.py --merge runs-off.jsonl runs-on.jsonl \
      --home-map on=<on>/home off=<off>/home --results results.json > tables.md
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(HERE, "..", "..", "squad-bench")
HOOK_BLOCK = "[BLOCKED BY HOOK]"
DECISION_PREFIXES = ("[DENIED]", "[BLOCKED BY AUTO MODE]", "[BUDGET REACHED]",
                     "[TOOL BUDGET REACHED]", "[CALL BUDGET REACHED]")


def dominant_string(v):
    """The largest string field of a result, like omnis's dominantString."""
    if isinstance(v, str):
        return v
    best = ""
    if isinstance(v, dict):
        for x in v.values():
            if isinstance(x, str) and len(x) > len(best):
                best = x
    return best


def classify(rec):
    """Port of agent/lessons_classify.go classifyToolFailure, on a recorded call."""
    if rec.get("error"):
        return True
    raw = rec.get("result")
    if raw is None:
        return False
    res = raw
    if isinstance(raw, str):
        try:
            res = json.loads(raw)
        except ValueError:
            res = raw
    if isinstance(res, dict) and "lesson" in res:
        # omnis classifies the result BEFORE it adds the hint note; the note
        # can be the longest string and would hide the error text.
        res = {k: v for k, v in res.items() if k != "lesson"}
    text = dominant_string(res).strip()
    if text.startswith(DECISION_PREFIXES):
        return False
    if text.startswith(HOOK_BLOCK):
        return True
    if isinstance(res, dict) and res.get("error") not in (None, ""):
        return True
    return text.startswith("Error") or text.startswith("error ")


def has_hint(rec):
    raw = rec.get("result")
    if isinstance(raw, dict):
        return "lesson" in raw
    if isinstance(raw, str):
        return '"lesson"' in raw
    return False


def walk_calls(turns):
    for t in turns:
        for c in t.get("tools") or []:
            yield "root", c
            for ch in c.get("children") or []:
                yield ch.get("agent") or "sub", ch


def load_turns(home, sid):
    path = os.path.join(home, "logs", f"conversation_{sid}.json")
    try:
        conv = json.load(open(path))
    except (OSError, ValueError):
        return None
    return (conv.get("turns") if isinstance(conv, dict) else conv) or []


def full_answer(turns):
    return "\n\n".join(t.get("assistant_text") or "" for t in turns or []).strip()


def tool_stats(turns):
    if turns is None:
        return {"conversation": None}
    s = {"root_calls": 0, "sub_calls": 0, "root_errors": 0, "sub_errors": 0,
         "hints": 0, "errors": [], "calls": []}
    for who, c in walk_calls(turns):
        key = "root" if who == "root" else "sub"
        s[key + "_calls"] += 1
        failed = classify(c)
        s["calls"].append({"agent": who, "name": c.get("name"), "failed": failed})
        if failed:
            s[key + "_errors"] += 1
            r = c.get("result")
            if isinstance(r, dict):
                r = {k: v for k, v in r.items() if k != "lesson"}
            s["errors"].append({"agent": who, "tool": c.get("name"),
                                "text": (dominant_string(r) or c.get("error") or "")[:160]})
        if has_hint(c):
            s["hints"] += 1
    return s


def _match(spec, text):
    if spec.startswith("/") and spec.endswith("/"):
        return re.search(spec[1:-1], text or "", re.I) is not None
    return spec.lower() in (text or "").lower()


def run_checks(task, cwd, answer, calls, file_check=None):
    """Return (correct, file_check). Check kinds:
      {"file": f, "match": re}  the file of the task's copy matches (needs cwd;
                                without one, the recorded file_check is reused)
      {"answer": re}            the final answer matches
      {"tool": name}            a recorded call of that tool succeeded
    """
    checks = task.get("check")
    if not checks:
        return None, None
    ok = True
    file_checks = [c for c in checks if "file" in c]
    if file_checks:
        if cwd is not None:
            file_check = True
            for c in file_checks:
                try:
                    text = open(os.path.join(cwd, c["file"])).read()
                except OSError:
                    text = None
                if text is None or not _match(c["match"], text):
                    file_check = False
        ok = ok and bool(file_check)
    for c in checks:
        if "answer" in c and not _match(c["answer"], answer):
            ok = False
        if "tool" in c and not any(x["name"] == c["tool"] and not x["failed"] for x in calls or []):
            ok = False
    return ok, file_check


def lessons_snapshot(home):
    out = []
    for p in sorted(glob.glob(os.path.join(home, "lessons", "*", "*.md"))):
        txt = open(p).read()
        m = re.match(r"---\n(.*?)\n---\n?(.*)", txt, re.S)
        fm = {}
        if m:
            for line in m.group(1).splitlines():
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
        fm["_body"] = (m.group(2) if m else txt).strip()
        out.append(fm)
    return out


def fresh_copy(task):
    src = os.path.join(HERE, "fixtures", task.get("fixture") or task["id"])
    tmp = tempfile.mkdtemp(prefix="lessons-" + task["id"] + "-")
    shutil.copytree(src, tmp, dirs_exist_ok=True)
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=b@b", "-c", "user.name=b", "commit", "-qm", "seed"]):
        subprocess.run(cmd, cwd=tmp, check=False)
    return tmp


def merge(args, tasks):
    """Re-score runner records offline (no model call) and print the report tables.

    Every record is re-read from its arm's conversation file (tool stats, full
    answer) and re-checked with the CURRENT tasks file. File checks cannot be
    re-run (the task copies are gone): the recorded `file_check` is reused.
    Records written before `file_check` existed carry the file result in
    `check` -- in this task set, every task with file checks had only file
    checks then, so `check` is the file result for those records.
    """
    homes = dict(h.split("=", 1) for h in args.home_map)
    by_id = {t["id"]: t for t in tasks}
    recs = []
    for path in args.merge:
        for line in open(path):
            if not line.strip():
                continue
            r = json.loads(line)
            task = by_id.get(r["task"])
            turns = load_turns(homes[r["arm"]], r["session_id"])
            r.update(tool_stats(turns))
            r["tool_calls"] = r.get("root_calls", 0) + r.get("sub_calls", 0)
            r["tool_errors"] = r.get("root_errors", 0) + r.get("sub_errors", 0)
            fc = r.get("file_check", r.get("check")) if task and any("file" in c for c in task.get("check") or []) else None
            if "correct_before_rescore" not in r:
                r["correct_before_rescore"] = r.get("correct")
            if task:
                r["check"], r["file_check"] = run_checks(task, None, full_answer(turns) or r.get("answer", ""),
                                                         r.get("calls"), fc)
                r["correct"] = r["check"] if r["check"] is not None else r.get("expect")
            recs.append(r)
    json.dump(recs, open(args.results, "w"), indent=1)
    cells = {}
    for r in recs:
        c = cells.setdefault((r["arm"], r["run"]), {"err": 0, "calls": 0, "hints": 0, "cost": 0.0,
                                                    "wall": 0, "ok": 0, "n": 0})
        c["err"] += r["tool_errors"]; c["calls"] += r["tool_calls"]; c["hints"] += r.get("hints", 0)
        c["cost"] += r["cost_usd"]; c["wall"] += r["wall_ms"]; c["ok"] += bool(r["correct"]); c["n"] += 1
    keys = sorted(cells, key=lambda k: (k[0] != "off", k[1]))
    print("| Arm | Run | Tool errors | Tool calls | Hints delivered | Cost | Wall | Correct |")
    print("|---|---|---|---|---|---|---|---|")
    for k in keys:
        c = cells[k]
        print(f"| {k[0]} | {k[1]} | {c['err']} | {c['calls']} | {c['hints']} | ${c['cost']:.3f}"
              f" | {round(c['wall'] / 1000)} s | {c['ok']}/{c['n']} |")
    print()
    print("| Task | " + " | ".join(f"{a} {n}" for a, n in keys) + " |")
    print("|---|" + "---|" * len(keys))
    for t in tasks:
        row = []
        for k in keys:
            r = next((x for x in recs if x["task"] == t["id"] and (x["arm"], x["run"]) == k), None)
            if r is None:
                row.append("-")
                continue
            failed = ", ".join(e["tool"] for e in r["errors"])
            row.append(f"{r['tool_errors']} / {r['tool_calls']}" + (f" {failed}" if failed else "")
                       + (" (hinted)" if r.get("hints") else "") + ("" if r["correct"] else " **wrong**"))
        print(f"| {t['id']} | " + " | ".join(row) + " |")
    changed = [r for r in recs if r["correct"] != r["correct_before_rescore"]]
    print(f"\nre-scored {len(recs)} records; correct changed on {len(changed)}:"
          + "".join(f"\n  {r['arm']} {r['run']} {r['task']}: {r['correct_before_rescore']} -> {r['correct']}"
                    for r in changed))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server")
    ap.add_argument("--token", default="bench")
    ap.add_argument("--home", help="the arm's OMNIS_HOME")
    ap.add_argument("--tasks", default=os.path.join(BENCH, "tasks-lessons.json"))
    ap.add_argument("--task", action="append", help="only these task ids")
    ap.add_argument("--arm")
    ap.add_argument("--run", type=int)
    ap.add_argument("--deadline", type=int, default=300)
    ap.add_argument("--out")
    ap.add_argument("--merge", nargs="+", metavar="JSONL",
                    help="offline: re-score these runner outputs, write --results, print the report tables")
    ap.add_argument("--home-map", nargs="+", default=[], metavar="ARM=HOME",
                    help="with --merge: the OMNIS_HOME of each arm")
    ap.add_argument("--results", default="results.json", help="with --merge: output file")
    args = ap.parse_args()

    tasks = json.load(open(args.tasks))["tasks"]
    if args.merge:
        merge(args, tasks)
        return
    if not (args.server and args.home and args.arm and args.run and args.out):
        ap.error("a run needs --server, --home, --arm, --run and --out (or use --merge)")
    if args.task:
        tasks = [t for t in tasks if t["id"] in args.task]
    for task in tasks:
        cwd = fresh_copy(task)
        p = subprocess.run([sys.executable, os.path.join(BENCH, "bench.py"),
                            "--server", args.server, "--token", args.token,
                            "--tasks", args.tasks, "--task", task["id"], "--cwd", cwd,
                            "--keep", "--json", "--deadline", str(args.deadline)],
                           capture_output=True, text=True)
        lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
        if not lines:
            print(f"[{task['id']}] bench.py failed: {p.stderr[-400:]}", file=sys.stderr)
            continue
        m = json.loads(lines[-1])
        rec = {
            "arm": args.arm, "run": args.run, "task": task["id"],
            "status": m["status"], "wall_ms": m["wall_ms"],
            "cost_usd": m["total_cost_usd"], "expect": m.get("correct"),
            "subagent_errors": len(m.get("subagent_errors") or []),
            "delegations": m.get("delegations"), "session_id": m.get("session_id"),
            "answer": (m.get("answer") or "")[:600],
        }
        turns = load_turns(args.home, m.get("session_id"))
        rec.update(tool_stats(turns))
        answer = full_answer(turns) or m.get("answer", "")
        rec["check"], rec["file_check"] = run_checks(task, cwd, answer, rec.get("calls"))
        rec["correct"] = rec["check"] if rec["check"] is not None else rec["expect"]
        rec["tool_calls"] = rec.get("root_calls", 0) + rec.get("sub_calls", 0)
        rec["tool_errors"] = rec.get("root_errors", 0) + rec.get("sub_errors", 0)
        with open(args.out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"[{args.arm} r{args.run}] {task['id']:<16} {rec['status']:<7} correct={rec['correct']}"
              f" calls={rec['tool_calls']} errors={rec['tool_errors']} hints={rec.get('hints')}"
              f" ${rec['cost_usd']:.4f} {rec['wall_ms']/1000:.0f}s")
        shutil.rmtree(cwd, ignore_errors=True)
    snap = os.path.splitext(args.out)[0] + f"-lessons-{args.arm}-run{args.run}.json"
    json.dump(lessons_snapshot(args.home), open(snap, "w"), indent=1)
    print(f"lessons snapshot: {snap}")


if __name__ == "__main__":
    main()
