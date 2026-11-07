#!/usr/bin/env python3
"""Budget guard for bench campaigns.

  budget.py check --ledger L --cap 58 [--add 9]   exit 1 if spent (+ planned) passes the cap
  budget.py stop --ref R.jsonl --arm A.jsonl      exit 1 if the arm must stop

Early stop: an arm stops once its cumulative cost exceeds `ratio` (1.5) times the
reference's cumulative cost on the same number of tasks, from the second task on.
Costs come from bench.py records (`total_cost_usd`, in run order).
"""
import argparse
import json
import sys
from pathlib import Path


def spent(ledger: Path) -> float:
    total = 0.0
    for line in Path(ledger).read_text().splitlines():
        if line.strip():
            total += float(json.loads(line).get("usd") or 0)
    return total


def record_costs(path: Path) -> list:
    return [float(json.loads(l).get("total_cost_usd") or 0)
            for l in Path(path).read_text().splitlines() if l.strip()]


def over_ratio(ref: list, arm: list, ratio: float = 1.5, min_tasks: int = 2) -> bool:
    n = min(len(ref), len(arm))
    if n < min_tasks:
        return False
    return sum(arm[:n]) > ratio * sum(ref[:n])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--ledger", required=True); c.add_argument("--cap", type=float, required=True)
    c.add_argument("--add", type=float, default=0.0)
    s = sub.add_parser("stop"); s.add_argument("--ref", required=True); s.add_argument("--arm", required=True)
    s.add_argument("--ratio", type=float, default=1.5)
    a = ap.parse_args()
    if a.cmd == "check":
        total = spent(a.ledger) + a.add
        print(f"spent+planned {total:.2f} $ / cap {a.cap:.2f} $")
        return 1 if total > a.cap else 0
    ref, arm = record_costs(a.ref), record_costs(a.arm)
    stop = over_ratio(ref, arm, a.ratio)
    print(f"arm {sum(arm):.3f} $ over {len(arm)} tasks vs ref {sum(ref[:len(arm)]):.3f} $ -> {'STOP' if stop else 'go'}")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
