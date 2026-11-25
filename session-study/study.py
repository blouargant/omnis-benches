#!/usr/bin/env python3
"""session-study — do scenarios built from real omnis sessions find defects our
hand-written bench tasks miss? One subcommand per step; see README.md.

Everything under out/ holds session text and is never committed.
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sessions
import signals


def default_logs():
    home = os.environ.get("OMNIS_HOME") or os.path.join(os.path.expanduser("~"), ".omnis")
    return os.path.join(home, "logs")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def scan_turns(sess):
    """One row per turn that has tool calls."""
    counts = collections.defaultdict(list)
    for s in sess:
        for t in s["turns"]:
            if t.get("tools"):
                counts[s["squad"]].append(sum(1 for _ in sessions.walk(t["tools"])))
    cut = {squad: signals.p90(c) for squad, c in counts.items()}
    rows = []
    for s in sess:
        for i, t in enumerate(s["turns"]):
            if not t.get("tools"):
                continue
            nxt = s["turns"][i + 1].get("user_text", "") if i + 1 < len(s["turns"]) else ""
            by_agent = collections.Counter(c.get("agent") or "root" for c, _ in sessions.walk(t["tools"]))
            rows.append({
                "turn_id": "%s#%d" % (s["id"], i), "session": s["id"], "turn": i, "squad": s["squad"],
                "skills": [k["name"] for k in s["skills"] if k["turn"] <= i],
                "calls": sum(by_agent.values()), "calls_by_agent": dict(by_agent),
                "tokens": t.get("usage") or {},
                "signals": signals.for_turn(t, nxt, cut[s["squad"]]),
                "user_text": t.get("user_text", ""), "reply": t.get("assistant_text", ""),
                "next_user_text": nxt, "outline": sessions.outline(t),
            })
    return rows


def cmd_scan(a):
    sess, summary = sessions.load(a.logs)
    rows = scan_turns(sess)
    os.makedirs(a.out, exist_ok=True)
    write_jsonl(os.path.join(a.out, "turns.jsonl"), rows)
    print("files: %(files)d  hidden: %(hidden)d  legacy: %(legacy)d  unreadable: %(unreadable)d" % summary)
    print("turns with tool calls: %d  by squad: %s" % (
        len(rows), dict(collections.Counter(r["squad"] for r in rows))))
    per = collections.Counter(s for r in rows for s in r["signals"])
    print("flagged turns: %d  by signal: %s" % (sum(1 for r in rows if r["signals"]), dict(per)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(HERE, "out"), help="working directory (session text; git-ignored)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan", help="read the session files and compute per-turn signals")
    p.add_argument("--logs", default=default_logs())
    p.set_defaults(fn=cmd_scan)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
