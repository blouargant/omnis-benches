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
import llm
import replay
import report
import review
import scenarios
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
                "at": t.get("at", ""),
                "skills": [k["name"] for k in s["skills"] if k["turn"] <= i],
                "calls": sum(by_agent.values()), "calls_by_agent": dict(by_agent),
                "tokens": t.get("usage") or {},
                "signals": signals.for_turn(t, nxt, cut[s["squad"]]),
                "user_text": t.get("user_text", ""), "reply": t.get("assistant_text", ""),
                "next_user_text": nxt, "outline": sessions.outline(t),
                "earlier_user_texts": [p.get("user_text", "") for p in s["turns"][max(0, i - 5):i]],
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
    gone = [c["card"] for c in cards if c["turn_id"] not in by_id]
    if gone:
        print("card(s) whose session is no longer scanned, left out of review.md: %s" % ", ".join(gone))
    save_json(cards_path, cards)
    intro = ("# Turns to review\n\nFor each card, say in `verdicts.json` whether the turn went wrong: "
             "`failure` = `yes`, `no` or `unsure`; `kind` = a few words naming what went wrong; "
             "`note` = anything useful (what you expected, a sign we do not record).\n\n")
    with open(os.path.join(a.out, "review.md"), "w", encoding="utf-8") as f:
        f.write(intro + "\n".join(review.card_markdown(c["card"], by_id[c["turn_id"]]) for c in cards if c["turn_id"] in by_id))
    if not os.path.exists(verdicts_path):
        save_json(verdicts_path, {c["card"]: {"failure": "", "kind": "", "note": ""} for c in cards})
    print("%d cards -> %s" % (len(cards), os.path.join(a.out, "review.md")))


def cmd_draft(a):
    cards = load_json(os.path.join(a.out, "cards.json"), [])
    verdicts, open_ = review.read_verdicts(os.path.join(a.out, "verdicts.json"))
    turns = {t["turn_id"]: t for t in read_jsonl(os.path.join(a.out, "turns.jsonl"))}
    if open_:
        print("%d card(s) still open or unsure, left out: %s" % (len(open_), ", ".join(open_)))
    drafts, sources, errors = scenarios.run_draft(cards, verdicts, turns, a.model)
    save_json(os.path.join(a.out, "scenarios-draft.json"), drafts)
    save_json(os.path.join(a.out, "sources.json"), sources)
    for e in errors:
        print("error: " + e)
    print("%d draft(s) -> %s" % (len(drafts), os.path.join(a.out, "scenarios-draft.json")))


def cmd_check(a):
    drafts = load_json(os.path.join(a.out, "scenarios-draft.json"), [])
    sources = load_json(os.path.join(a.out, "sources.json"), {})
    turns = {t["turn_id"]: t for t in read_jsonl(os.path.join(a.out, "turns.jsonl"))}
    allowed_path = os.path.join(a.out, "allowed.json")
    allowed = sorted(set(load_json(allowed_path, [])) | {x.strip() for x in a.allow.split(",") if x.strip()})
    save_json(allowed_path, allowed)
    texts = {sid: scenarios.source_text(turns[tid]) for sid, tid in sources.items() if tid in turns}
    traces = {sid: scenarios.trace_text(turns[tid]) for sid, tid in sources.items() if tid in turns}
    dirty = 0
    for d in drafts:
        found = scenarios.leaks(texts.get(d["id"], ""), d, allowed, traces.get(d["id"], ""))
        dirty += bool(found)
        print("%-6s %s" % (d["id"], "LEAKS: " + ", ".join(found) if found else "clean"))
    if allowed:
        print("allowed by hand: " + ", ".join(allowed))
    if a.accept:
        ids = [x.strip() for x in a.accept.split(",") if x.strip()]
        try:
            kept = scenarios.accept(drafts, texts, ids, allowed, traces)
        except ValueError as e:
            sys.exit("not accepted: %s" % e)
        current = {t["id"]: t for t in load_json(a.tasks, [])}
        current.update({d["id"]: d for d in kept})
        save_json(a.tasks, [current[k] for k in sorted(current)])
        print("%d scenario(s) in %s" % (len(current), a.tasks))
        return 0
    return 1 if dirty else 0


def cmd_replay(a):
    tasks = load_json(a.tasks, [])
    if not tasks:
        sys.exit("no accepted scenario in %s: run `check --accept` first" % a.tasks)
    tasks_path = replay.materialise(tasks, a.out)

    def judge_run(scenario, record):
        system, user = judge.run_prompt(scenario, record)
        text, _ = llm.call(a.judge_model, system, user)
        return judge.parse_run(text)

    s = replay.run_replay(tasks, a.out, a.repeat, a.ceiling,
                          replay.bench_runner(a.server, a.token, tasks_path, a.deadline), judge_run)
    print("runs started: %d  spent: $%.2f of $%.2f%s" % (
        s["runs"], replay.spent(os.path.join(a.out, "ledger.jsonl")), a.ceiling,
        "  (stopped at the ceiling)" if s["stopped"] == "ceiling" else ""))
    judged = replay.judged_by_scenario(a.out)
    for t in tasks:
        o = replay.outcome(t, judged.get(t["id"], []))
        print("%-6s %-18s runs %d  invalid %d  passed %d  failure seen %d" % (
            t["id"], o["status"], o["runs"], o["invalid"], o["passed"], o["failure_seen"]))


def cmd_report(a):
    import datetime
    date = a.date or datetime.date.today().isoformat()
    path = os.path.join(HERE, "..", "reports", "session-scenarios-knowledge-%s.md" % date)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report.build(a.out, a.tasks))
    print("report -> %s" % os.path.normpath(path))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(HERE, "out"), help="working directory (session text; git-ignored)")
    ap.add_argument("--tasks", default=os.path.join(HERE, "tasks-sessions.json"),
                    help="the accepted scenarios (the one committed file with scenario text)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan", help="read the session files and compute per-turn signals")
    p.add_argument("--logs", default=default_logs())
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("judge", help="one model verdict per scanned turn")
    p.add_argument("--model", default="claude-sonnet-5-5", help="gateway model id (default: the one behind `premium`)")
    p.set_defaults(fn=cmd_judge)
    p = sub.add_parser("review", help="write the cards to read and the verdict file to fill")
    p.set_defaults(fn=cmd_review)
    p = sub.add_parser("draft", help="draft a scenario per confirmed failure, plus two controls")
    p.add_argument("--model", default="claude-sonnet-5-5")
    p.set_defaults(fn=cmd_draft)
    p = sub.add_parser("check", help="list session text left in the drafts; --accept copies clean ones to --tasks")
    p.add_argument("--allow", default="", help="comma list of tokens a scenario may keep (public product names)")
    p.add_argument("--accept", default="", help="comma list of draft ids to accept")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("replay", help="run the accepted scenarios with squad-bench and judge each run")
    p.add_argument("--server", required=True)
    p.add_argument("--token", default=os.environ.get("OMNIS_SERVER_TOKEN", ""))
    p.add_argument("--repeat", type=int, default=5)
    p.add_argument("--ceiling", type=float, default=30.0, help="stop starting runs at this many dollars")
    p.add_argument("--deadline", type=int, default=900, help="per-turn cap passed to bench.py (s)")
    p.add_argument("--judge-model", default="gpt-5.5", help="another family than the model that answered")
    p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("report", help="write the study report under reports/")
    p.add_argument("--date", default="", help="YYYY-MM-DD (default: today)")
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
