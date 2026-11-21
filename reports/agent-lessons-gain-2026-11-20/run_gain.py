#!/usr/bin/env python3
"""Run squad-bench/tasks-lessons-gain.json once, in order, against one running
omnis-server (one arm, one repetition). Each task gets a fresh git-seeded copy
of the fixture, so a trap is met again in every session; what carries over is
only what omnis keeps in its home (the lessons).

Measured per session, independently of omnis's own error classification:
trap hits (Bash results carrying the trap's error marker), tool calls, model
calls, tokens, cost, wall time, hints delivered, correct.

  run_gain.py --server http://127.0.0.1:18401 --home <home> --arm on --rep 1 --out runs.jsonl
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(HERE, "..", "..", "squad-bench")


def text_of(raw):
    if isinstance(raw, (dict, list)):
        return json.dumps(raw)
    return raw or ""


def load_turns(home, sid):
    try:
        conv = json.load(open(os.path.join(home, "logs", f"conversation_{sid}.json")))
    except (OSError, ValueError):
        return None
    return (conv.get("turns") if isinstance(conv, dict) else conv) or []


def walk(turns):
    for t in turns or []:
        for c in t.get("tools") or []:
            yield c
            for ch in c.get("children") or []:
                yield ch


def lessons(home):
    out = []
    for p in sorted(glob.glob(os.path.join(home, "lessons", "*", "*.md"))):
        txt = open(p).read()
        m = re.match(r"---\n(.*?)\n---\n?(.*)", txt, re.S)
        fm = {}
        for line in (m.group(1).splitlines() if m else []):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
        fm["_body"] = (m.group(2) if m else txt).strip()
        out.append(fm)
    return out


def fresh_copy(task):
    tmp = tempfile.mkdtemp(prefix="gain-" + task["id"] + "-")
    shutil.copytree(os.path.join(HERE, "fixtures", task["fixture"]), tmp, dirs_exist_ok=True)
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=b@b", "-c", "user.name=b", "commit", "-qm", "seed"]):
        subprocess.run(cmd, cwd=tmp, check=False)
    return tmp


def match(spec, text):
    return re.search(spec[1:-1], text or "", re.I) is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--token", default="bench")
    ap.add_argument("--home", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--rep", type=int, required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--tasks", default=os.path.join(BENCH, "tasks-lessons-gain.json"))
    ap.add_argument("--task", action="append")
    ap.add_argument("--deadline", type=int, default=300)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tasks = json.load(open(a.tasks))["tasks"]
    if a.task:
        tasks = [t for t in tasks if t["id"] in a.task]
    for pos, task in enumerate(tasks, 1):
        cwd = fresh_copy(task)
        p = subprocess.run([sys.executable, os.path.join(BENCH, "bench.py"), "--server", a.server,
                            "--token", a.token, "--tasks", a.tasks, "--task", task["id"], "--cwd", cwd,
                            "--keep", "--json", "--deadline", str(a.deadline)], capture_output=True, text=True)
        lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
        if not lines:
            print(f"[{task['id']}] bench.py failed: {p.stderr[-300:]}", file=sys.stderr)
            shutil.rmtree(cwd, ignore_errors=True)
            continue
        m = json.loads(lines[-1])
        turns = load_turns(a.home, m.get("session_id"))
        calls = list(walk(turns))
        answer = "\n".join(t.get("assistant_text") or "" for t in turns or []) or m.get("answer", "")
        ok = True
        for c in task["check"]:
            if "answer" in c:
                ok = ok and match(c["answer"], answer)
            if "file" in c:
                try:
                    ok = ok and match(c["match"], open(os.path.join(cwd, c["file"])).read())
                except OSError:
                    ok = False
        mk = task.get("marker")
        models = m.get("models") or {}
        ls = lessons(a.home)
        rec = {
            "model": a.model, "arm": a.arm, "rep": a.rep, "pos": pos, "task": task["id"], "trap": task["trap"],
            "trap_kind": task["trap_kind"], "exposure": task["exposure"], "status": m["status"],
            "correct": bool(ok), "wall_ms": m["wall_ms"], "cost_usd": m["total_cost_usd"],
            "tool_calls": len(calls) if turns is not None else len(m.get("tool_calls") or []),
            "model_calls": sum(x.get("calls", 0) for x in models.values()),
            "prompt_tok": sum(x.get("prompt_tok", 0) for x in models.values()),
            "out_tok": sum(x.get("out_tok", 0) for x in models.values()),
            "trap_hits": sum(1 for c in calls if mk and c.get("name") == "Bash" and mk in text_of(c.get("result"))
                             and "#!/bin/sh" not in text_of(c.get("result"))),
            "hints": sum(1 for c in calls if '"lesson"' in text_of(c.get("result"))),
            "tools": [c.get("name") for c in calls],
            "bash": [text_of(c.get("args"))[:160] for c in calls if c.get("name") == "Bash"],
            "lessons_n": len(ls), "lessons_prompt": sum(1 for l in ls if l.get("state") == "prompt"),
            "session_id": m.get("session_id"), "answer": answer[-200:],
        }
        with open(a.out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"[{a.arm} r{a.rep} {pos:02d}] {task['id']:<10} ok={rec['correct']!s:<5} hits={rec['trap_hits']} "
              f"hints={rec['hints']} tools={rec['tool_calls']} mcalls={rec['model_calls']} "
              f"${rec['cost_usd']:.4f} {rec['wall_ms']/1000:.0f}s lessons={rec['lessons_n']}/{rec['lessons_prompt']}p", flush=True)
        shutil.rmtree(cwd, ignore_errors=True)
    json.dump(lessons(a.home), open(os.path.splitext(a.out)[0] + f"-lessons-{a.arm}-r{a.rep}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
