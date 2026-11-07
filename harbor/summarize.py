#!/usr/bin/env python3
"""Summarise one or more Harbor job directories (stdlib only).

    python3 summarize.py jobs/<job> [jobs/<job2> ...] [--jsonl out.jsonl]

One row per trial: task, variant, reward (resolved = reward >= 1, the
leaderboard's binary resolve), tokens (prompt incl. cache / cached / output),
model calls, tool calls, USD cost, agent wall time, and the exception if the
trial did not complete (an infra error is NOT a fail — the leaderboard retries
then excludes them, so they are reported apart). Then per (job) totals:
resolve rate over scored trials, mean cost per trial, cost per resolved task.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def _secs(t: dict | None) -> float | None:
    if not t or not t.get("started_at") or not t.get("finished_at"):
        return None
    f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    return (f(t["finished_at"]) - f(t["started_at"])).total_seconds()


def trial_row(result: dict) -> dict:
    ar = result.get("agent_result") or {}
    meta = ar.get("metadata") or {}
    vr = result.get("verifier_result") or {}
    rewards = vr.get("rewards") or {}
    reward = rewards.get("reward", next(iter(rewards.values()), None) if rewards else None)
    exc = result.get("exception_info")
    kw = ((result.get("config") or {}).get("agent") or {}).get("kwargs") or {}
    return {
        "task": result.get("task_name"),
        "trial": result.get("trial_name"),
        "variant": meta.get("variant") or kw.get("variant"),
        "model": ((result.get("agent_info") or {}).get("model_info") or {}).get("name"),
        "reward": reward,
        "resolved": None if reward is None else bool(reward >= 1),
        "prompt_tok": ar.get("n_input_tokens"),
        "cache_tok": ar.get("n_cache_tokens"),
        "out_tok": ar.get("n_output_tokens"),
        "cost_usd": ar.get("cost_usd"),
        "model_calls": meta.get("model_calls"),
        "tool_calls": meta.get("tool_calls"),
        "agents": sorted((meta.get("agents") or {}).keys()),
        "agent_s": _secs(result.get("agent_execution")),
        "trial_s": _secs({"started_at": result.get("started_at"), "finished_at": result.get("finished_at")}),
        "exception": (exc or {}).get("exception_type"),
        "exception_msg": ((exc or {}).get("exception_message") or "")[:200] or None,
    }


def load(job: Path) -> list[dict]:
    rows = []
    for r in sorted(job.glob("*/result.json")):
        rows.append(trial_row(json.loads(r.read_text())))
    return rows


def totals(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["resolved"] is not None]
    solved = [r for r in scored if r["resolved"]]
    cost = sum(r["cost_usd"] or 0 for r in scored)
    return {
        "trials": len(rows), "scored": len(scored), "resolved": len(solved),
        "resolve_rate": len(solved) / len(scored) if scored else None,
        "infra_errors": len(rows) - len(scored),
        "cost_usd": cost,
        "cost_per_trial": cost / len(scored) if scored else None,
        "cost_per_resolved": cost / len(solved) if solved else None,
        "prompt_tok": sum(r["prompt_tok"] or 0 for r in scored),
        "out_tok": sum(r["out_tok"] or 0 for r in scored),
    }


def _fmt(v, nd=3):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="+", type=Path)
    ap.add_argument("--jsonl", type=Path)
    a = ap.parse_args()
    out = []
    for job in a.jobs:
        rows = load(job)
        print(f"\n== {job.name}")
        print(f"{'task':40} {'var':5} {'rew':>4} {'prompt':>9} {'cached':>9} {'out':>7} {'calls':>5} {'tools':>5} {'$':>7} {'agent_s':>7}  exc")
        for r in rows:
            print(f"{(r['task'] or '')[-40:]:40} {r['variant'] or '':5} {_fmt(r['reward'],0):>4} "
                  f"{_fmt(r['prompt_tok']):>9} {_fmt(r['cache_tok']):>9} {_fmt(r['out_tok']):>7} "
                  f"{_fmt(r['model_calls']):>5} {_fmt(r['tool_calls']):>5} {_fmt(r['cost_usd'],4):>7} "
                  f"{_fmt(r['agent_s'],0):>7}  {r['exception'] or ''}")
            out.append({"job": job.name, **r})
        t = totals(rows)
        print("   totals:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()})
    if a.jsonl:
        with a.jsonl.open("a") as f:
            for r in out:
                f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()
