"""Run the accepted scenarios with squad-bench, judge each run, and say which
failures reproduce."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(HERE, "..", "squad-bench", "bench.py")
INVALID_STATUS = ("timeout", "cancelled", "ask_user", "error")


def _append(path, row):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _safe_name(name):
    if (not name or "\\" in name or os.path.isabs(name)
            or ".." in name.replace("\\", "/").split("/")):
        raise ValueError("scenario file name %r leaves its fixture directory" % name)
    return name


def materialise(scenarios, out_dir):
    """Write each scenario's files under out_dir/fixtures/<id>/ and a squad-bench
    tasks file without rubric or files. Returns the tasks file's path."""
    tasks = []
    for s in scenarios:
        task = {k: s[k] for k in ("id", "squad", "prompt", "prompts", "kind") if s.get(k)}
        files = s.get("files") or {}
        for name in files:
            _safe_name(name)
        if files:
            root = os.path.abspath(os.path.join(out_dir, "fixtures", s["id"]))
            for name, content in files.items():
                path = os.path.join(root, name)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            task["cwd"] = root
        tasks.append(task)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "tasks-replay.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=1)
    return path


def spent(ledger_path):
    return sum(float(r.get("cost") or 0) for r in _rows(ledger_path))


def valid(record):
    """A run that can be judged: it finished and answered."""
    return (record.get("status") == "done") and bool((record.get("answer") or "").strip())


def outcome(scenario, judged_runs):
    """Counts and status of one scenario. An invalid run is never a failure seen."""
    good = [r for r in judged_runs if r.get("valid") and "error" not in r]
    invalid = len(judged_runs) - len(good)
    passed = sum(1 for r in good if r.get("passed"))
    seen = sum(1 for r in good if r.get("failure_seen"))
    control = not (scenario.get("rubric") or {}).get("failure")
    if invalid > 2 or len(judged_runs) == 0:
        status = "not_measured"
    elif control:
        status = "control_ok" if passed >= 4 else "control_fails" if len(judged_runs) >= 5 else "not_measured"
    elif seen >= 2:
        status = "reproduces"
    else:
        status = "does_not_reproduce" if len(good) >= 3 else "not_measured"
    return {"runs": len(judged_runs), "invalid": invalid, "passed": passed, "failure_seen": seen, "status": status}


def bench_runner(server, token, tasks_path, deadline):
    """run(task_id) -> one squad-bench record, from a bench.py subprocess."""
    def run(task_id):
        cmd = [sys.executable, BENCH, "--server", server, "--token", token, "--tasks", tasks_path,
               "--task", task_id, "--nonce", "--deadline", str(deadline), "--json"]
        p = subprocess.run(cmd, capture_output=True, text=True)
        lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
        if p.returncode != 0 or not lines:
            raise RuntimeError("bench.py failed for %s (exit %d): %s" % (
                task_id, p.returncode, (p.stderr or p.stdout).strip()[-400:]))
        return json.loads(lines[-1])
    return run


def run_replay(scenarios, out_dir, repeat, ceiling, run, judge_run):
    """Bring every scenario to `repeat` runs, judging each valid one. Stops when
    the ledger reaches `ceiling` dollars. Resumable: existing runs are kept,
    and a run whose judging failed is judged again."""
    os.makedirs(out_dir, exist_ok=True)
    runs_path = os.path.join(out_dir, "runs.jsonl")
    ledger_path = os.path.join(out_dir, "ledger.jsonl")
    judged_path = os.path.join(out_dir, "run-judged.jsonl")
    summary = {"runs": 0, "stopped": "done"}
    for s in scenarios:
        have = sum(1 for r in _rows(runs_path) if r.get("task") == s["id"])
        for _ in range(max(0, repeat - have)):
            if spent(ledger_path) >= ceiling:
                summary["stopped"] = "ceiling"
                break
            record = run(s["id"])
            record["task"] = s["id"]
            _append(runs_path, record)
            _append(ledger_path, {"scenario": s["id"], "cost": float(record.get("total_cost_usd") or 0)})
            summary["runs"] += 1
        if summary["stopped"] == "ceiling":
            break
    _judge_pending(scenarios, runs_path, judged_path, judge_run)
    return summary


def _judge_pending(scenarios, runs_path, judged_path, judge_run):
    by_id = {s["id"]: s for s in scenarios}
    done = {(r["scenario"], r["run"]): r for r in _rows(judged_path)}
    index = {}
    for record in _rows(runs_path):
        sid = record.get("task")
        n = index.get(sid, 0)
        index[sid] = n + 1
        key = (sid, n)
        if sid not in by_id or (key in done and "error" not in done[key]):
            continue
        row = {"scenario": sid, "run": n, "valid": valid(record), "passed": False, "failure_seen": False}
        if not row["valid"]:
            row["reason"] = "invalid run: %s" % (record.get("status") or "no status"
                                                 if record.get("status") != "done" else "empty answer")
        else:
            try:
                row.update(judge_run(by_id[sid], record))
            except Exception as e:  # judged again on the next run
                row["error"] = "%s: %s" % (type(e).__name__, e)
        done[key] = row
    tmp = judged_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for key in sorted(done):
            f.write(json.dumps(done[key], ensure_ascii=False) + "\n")
    os.replace(tmp, judged_path)


def judged_by_scenario(out_dir):
    out = {}
    for r in _rows(os.path.join(out_dir, "run-judged.jsonl")):
        out.setdefault(r["scenario"], []).append(r)
    return out
