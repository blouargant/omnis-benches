"""The study's report: funnel, precision, scenarios, coverage, verdict.
Scenario text comes from the accepted tasks file only; session text never."""
import collections
import json
import os

import replay
import review

RULE = ("Fixed before the study: go on to a failure marker in omnis when 3 or more distinct failures "
        "reproduce and no existing suite covers them; stop when none does; 1 or 2 is undecided.")
MISSING = ["a Stop by the user (not recorded)", "a rewind (it deletes the turns it rewinds)",
           "tool calls of injected turns (scheduled, mailbox, spawned)", "the files' state at the time of the turn"]
LIMITS = [
    "One user, one machine, a few weeks of recorded tool calls, mostly one squad.",
    "Live web: a scenario's result can change with the web, not only with omnis.",
    "Stop and rewind, the two clearest signs of an unhappy user, are invisible.",
    "The same model family may write the scenarios and judge the turns.",
    "A reproduced failure shows the scenario is a usable test; it does not show that fixing it improves real sessions.",
]
STATUS = {"reproduces": "reproduces", "does_not_reproduce": "does not reproduce", "not_measured": "not measured",
          "control_ok": "control ok", "control_fails": "control fails"}


def _json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def decide(outcomes, coverage):
    """("go"|"stop"|"undecided", n): n distinct failures that reproduce and that
    no existing suite covers. ValueError when a reproducing scenario has no coverage line."""
    reproducing = sorted(sid for sid, o in outcomes.items() if o.get("status") == "reproduces")
    missing = [sid for sid in reproducing if sid not in coverage]
    if missing:
        raise ValueError("coverage.json has no entry for: %s" % ", ".join(missing))
    groups = {coverage[sid].get("group") or sid for sid in reproducing if not coverage[sid].get("covered_by")}
    n = len(groups)
    return ("go" if n >= 3 else "stop" if n == 0 else "undecided"), n


def _table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _pct(p):
    return "–" if p is None else "%d %%" % round(100 * p)


def build(out_dir, tasks_path):
    turns = _jsonl(os.path.join(out_dir, "turns.jsonl"))
    judged_rows = _jsonl(os.path.join(out_dir, "judged.jsonl"))
    judged = {r["turn_id"]: r for r in judged_rows if "error" not in r}
    cards = _json(os.path.join(out_dir, "cards.json"), [])
    verdicts, open_cards = review.read_verdicts(os.path.join(out_dir, "verdicts.json"))
    tasks = _json(tasks_path, [])
    coverage = _json(os.path.join(out_dir, "coverage.json"), {})
    runs = replay.judged_by_scenario(out_dir)
    costs = collections.defaultdict(float)
    for r in _jsonl(os.path.join(out_dir, "ledger.jsonl")):
        costs[r.get("scenario")] += float(r.get("cost") or 0)

    by_id = {t["turn_id"]: t for t in turns}
    flagged = [t for t in turns if t.get("signals")
               or (judged.get(t["turn_id"]) or {}).get("verdict") in ("failed", "wasteful")]
    confirmed = sum(1 for v in verdicts.values() if v["failure"] == "yes")
    failures = [t for t in tasks if (t.get("rubric") or {}).get("failure")]
    controls = [t for t in tasks if not (t.get("rubric") or {}).get("failure")]
    outcomes = {t["id"]: replay.outcome(t, runs.get(t["id"], [])) for t in tasks}
    reproducing = [t["id"] for t in failures if outcomes[t["id"]]["status"] == "reproduces"]
    try:
        verdict, n = decide({t["id"]: outcomes[t["id"]] for t in failures}, coverage)
        verdict_line = "**%s** — %d distinct failure(s) reproduce and are not covered by an existing suite." % (verdict, n)
    except ValueError as e:
        n, verdict_line = None, "**not decided** — %s. Fill `out/coverage.json`, then run `report` again." % e

    dates = sorted(t.get("at", "")[:10] for t in turns if t.get("at"))
    squads = collections.Counter(t.get("squad") or "?" for t in turns)
    md = ["# Scenarios from real sessions — study report", ""]
    md += ["## Scope", "",
           "One machine. %d recorded turns with tool calls, from %s to %s. By squad: %s." % (
               len(turns), dates[0] if dates else "?", dates[-1] if dates else "?",
               ", ".join("%s %d" % kv for kv in squads.most_common())), ""]
    md += ["## Funnel", "", _table(["Step", "Count"], [
        ["Turns scanned", len(turns)], ["Flagged", len(flagged)], ["Cards reviewed", len(verdicts)],
        ["Confirmed failures", confirmed], ["Scenarios", len(failures)],
        ["Reproduce", len(reproducing)], ["Not covered", "?" if n is None else n]]), ""]
    if open_cards:
        md += ["Cards still open or marked unsure, left out of every figure: %s." % ", ".join(open_cards), ""]

    prec = review.precision(cards, verdicts, by_id, judged)
    md += ["## Precision of each way of flagging a turn", "",
           _table(["Method", "Turns flagged", "Checked", "Real failures", "Precision"],
                  [[name, r["flagged"], r["checked"], r["real"], _pct(r["precision"])]
                   for name, r in prec["rows"].items()]), "",
           "Turns nobody flagged, drawn at random: %d checked, %d were real failures." % (
               prec["controls_checked"], prec["controls_real"]), ""]

    rows = []
    for t in tasks:
        o = outcomes[t["id"]]
        rows.append([t["id"], t["squad"], (t.get("rubric") or {}).get("failure") or "(control)",
                     "%d (%d invalid)" % (o["runs"], o["invalid"]), o["failure_seen"], o["passed"],
                     STATUS[o["status"]], "$%.2f" % costs.get(t["id"], 0.0)])
    md += ["## Scenarios", "",
           _table(["Id", "Squad", "Failure looked for", "Runs", "Failure seen", "Passed", "Status", "Cost"], rows), ""]

    md += ["## Coverage by existing suites", ""]
    if reproducing:
        md += [_table(["Id", "Group", "Covered by"],
                      [[sid, (coverage.get(sid) or {}).get("group", "?"),
                        (coverage.get(sid) or {}).get("covered_by") or ("none" if sid in coverage else "?")]
                       for sid in reproducing]), ""]
    else:
        md += ["No scenario reproduces.", ""]

    extra = sorted({s for c in coverage.values() for s in (c.get("missing_signals") or [])})
    md += ["## Signals that were missing", ""] + ["- " + s for s in MISSING + extra] + [""]

    judge_tokens = sum(int((r.get("usage") or {}).get("total_tokens") or 0) for r in judged_rows)
    md += ["## Spend", "",
           "Replay: $%.2f. Turn judge: %d tokens." % (sum(costs.values()), judge_tokens), ""]

    bad_controls = [t["id"] for t in controls if outcomes[t["id"]]["status"] == "control_fails"]
    if bad_controls:
        md += ["> Warning: control scenario(s) %s fail. The replay or its judge may be failing everything; "
               "read the verdict with that in mind." % ", ".join(bad_controls), ""]
    md += ["## Verdict", "", verdict_line, "", RULE, ""]
    md += ["## Limits", ""] + ["- " + l for l in LIMITS] + [""]
    return "\n".join(md)
