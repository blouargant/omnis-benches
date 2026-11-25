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

import judge
import review
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


def cmd_judge(a):
    turns = read_jsonl(os.path.join(a.out, "turns.jsonl"))
    if not turns:
        sys.exit("no out/turns.jsonl: run `scan` first")
    path = os.path.join(a.out, "judged.jsonl")
    s = judge.run_judge(turns, path, a.model)
    print("judged: %(judged)d  errors: %(errors)d  already done: %(skipped)d" % s)
    rows = [r for r in read_jsonl(path) if "error" not in r]
    print("verdicts: %s" % dict(collections.Counter(r["verdict"] for r in rows)))
    if s["errors"]:
        print("re-run `judge` to retry the %d error(s)" % s["errors"])


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def judged_by_turn(out):
    return {r["turn_id"]: r for r in read_jsonl(os.path.join(out, "judged.jsonl")) if "error" not in r}


def cmd_review(a):
    turns = read_jsonl(os.path.join(a.out, "turns.jsonl"))
    if not turns:
        sys.exit("no out/turns.jsonl: run `scan` first")
    judged = judged_by_turn(a.out)
    if len(judged) < len(turns):
        print("warning: %d turn(s) have no judge verdict yet" % (len(turns) - len(judged)))
    cards_path, verdicts_path = os.path.join(a.out, "cards.json"), os.path.join(a.out, "verdicts.json")
    if os.path.exists(cards_path) and os.path.exists(verdicts_path):
        # The answers in verdicts.json are keyed by card number: never renumber under them.
        cards = load_json(cards_path, [])
        print("cards.json kept: verdicts.json exists (delete both to pick the cards again)")
    else:
        cards = review.pick(turns, judged)
    by_id = {t["turn_id"]: t for t in turns}
    save_json(cards_path, cards)
    intro = ("# Turns to review\n\nFor each card, say in `verdicts.json` whether the turn went wrong: "
             "`failure` = `yes`, `no` or `unsure`; `kind` = a few words naming what went wrong; "
             "`note` = anything useful (what you expected, a sign we do not record).\n\n")
    with open(os.path.join(a.out, "review.md"), "w", encoding="utf-8") as f:
        f.write(intro + "\n".join(review.card_markdown(c["card"], by_id[c["turn_id"]]) for c in cards))
    if not os.path.exists(verdicts_path):
        save_json(verdicts_path, {c["card"]: {"failure": "", "kind": "", "note": ""} for c in cards})
    print("%d cards -> %s" % (len(cards), os.path.join(a.out, "review.md")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(HERE, "out"), help="working directory (session text; git-ignored)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan", help="read the session files and compute per-turn signals")
    p.add_argument("--logs", default=default_logs())
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("judge", help="one model verdict per scanned turn")
    p.add_argument("--model", default="claude-sonnet-5-5", help="gateway model id (default: the one behind `premium`)")
    p.set_defaults(fn=cmd_judge)
    p = sub.add_parser("review", help="write the cards to read and the verdict file to fill")
    p.set_defaults(fn=cmd_review)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
