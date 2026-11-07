#!/usr/bin/env python3
"""Summarise requests.jsonl: first request of each agent, tokens ≈ chars/4."""
import json, sys
T = lambda s: (len(s) + 3) // 4
seen = {}
for line in open(sys.argv[1]):
    r = json.loads(line)
    if r["agent"] not in seen:
        seen[r["agent"]] = r
rows = []
for a, r in seen.items():
    tools = sorted(((t["function"]["name"], T(json.dumps(t))) for t in r["tools"]), key=lambda x: -x[1])
    rows.append((a, T(r["system"]), len(tools), sum(c for _, c in tools), tools))
rows.sort(key=lambda x: -(x[1] + x[3]))
print(f"{'agent':22} {'total':>7} {'instr':>7} {'tools':>6} {'tool tok':>8}")
for a, si, n, tt, _ in rows:
    print(f"{a:22} {si+tt:7d} {si:7d} {n:6d} {tt:8d}")
print(f"{'SUM':22} {sum(r[1]+r[3] for r in rows):7d}")
if "-v" in sys.argv:
    for a, si, n, tt, tools in rows:
        print(f"\n## {a}")
        for name, c in tools:
            print(f"  {c:6d} {name}")
