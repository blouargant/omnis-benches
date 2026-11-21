#!/usr/bin/env python3
"""Tables for the lessons-gain bench, from run_gain.py records.

  analyze.py LABEL=runs.jsonl [LABEL=more.jsonl ...]

Each file is one run (several repetitions of both arms). The `off` arms of all
files are pooled into one baseline (lessons off does not depend on the build);
each file's `on` arm is a condition named by its LABEL.

A session with no model call or an empty answer is an infrastructure failure
(the gateway returned nothing): it is excluded and counted.

Exposure 1 is the same situation in every condition (no lesson can exist yet),
so the comparison that matters is exposures 2-5. The unit is one repetition:
its mean per session. The p-value is a two-sided permutation test on those
per-repetition means (20,000 shuffles, fixed seed) against the pooled baseline.
"""
import json, random, sys

METRICS = [("trap_hits", "Trap hits"), ("tool_calls", "Tool calls"), ("model_calls", "Model calls"),
           ("prompt_tok", "Prompt tokens"), ("cost_usd", "Cost $"), ("wall_s", "Wall s")]


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def perm_p(a, b, n=20000):
    if not a or not b:
        return float("nan")
    rnd = random.Random(1)
    pool = a + b
    obs = abs(mean(a) - mean(b))
    hits = 0
    for _ in range(n):
        rnd.shuffle(pool)
        if abs(mean(pool[:len(a)]) - mean(pool[len(a):])) >= obs - 1e-12:
            hits += 1
    return hits / n


def fmt(v, key):
    return f"{v:.4f}" if key == "cost_usd" else f"{v:,.0f}" if key == "prompt_tok" else f"{v:.2f}"


def valid(r):
    return r.get("status") == "done" and r.get("model_calls", 0) > 0 and (r.get("answer") or "").strip() != ""


def per_rep(rs, key, pred):
    out = {}
    for r in rs:
        if pred(r):
            out.setdefault((r["file"], r["rep"]), []).append(r[key])
    return [mean(v) for v in out.values()]


def main():
    conds, order = {"off": []}, ["off"]
    dropped = {}
    for arg in sys.argv[1:]:
        label, path = arg.split("=", 1)
        for l in open(path):
            if not l.strip():
                continue
            r = json.loads(l)
            r["file"] = path
            r["wall_s"] = r["wall_ms"] / 1000
            c = "off" if r["arm"] == "off" else label
            if c not in conds:
                conds[c] = []
                order.append(c)
            if not valid(r):
                dropped[c] = dropped.get(c, 0) + 1
                continue
            conds[c].append(r)
    print("Sessions kept / excluded as infrastructure failures: "
          + ", ".join(f"{c} {len(conds[c])} / {dropped.get(c, 0)}" for c in order) + "\n")

    scopes = [("Trap tasks, exposures 2-5", lambda r: r["trap_kind"] != "control" and r["exposure"] >= 2),
              ("Opaque traps, exposures 2-5", lambda r: r["trap_kind"] == "opaque" and r["exposure"] >= 2),
              ("Explicit traps, exposures 2-5", lambda r: r["trap_kind"] == "explicit" and r["exposure"] >= 2),
              ("Trap tasks, exposure 1 (no lesson can exist: should not differ)", lambda r: r["trap_kind"] != "control" and r["exposure"] == 1),
              ("Control tasks (no trap), all exposures", lambda r: r["trap_kind"] == "control"),
              ("All 25 sessions", lambda r: True)]
    for title, pred in scopes:
        print(f"### {title} — mean per session\n")
        print("| Metric | " + " | ".join(order) + " |")
        print("|---|" + "---|" * len(order))
        base = {k: per_rep(conds["off"], k, pred) for k, _ in METRICS}
        for key, label in METRICS:
            cells = [fmt(mean(base[key]), key)]
            for c in order[1:]:
                x = per_rep(conds[c], key, pred)
                a, b = mean(base[key]), mean(x)
                cells.append(f"{fmt(b, key)} ({(b - a) / a * 100:+.0f} %, p={perm_p(base[key], x):.2f})" if a else fmt(b, key))
            print(f"| {label} | " + " | ".join(cells) + " |")
        cells = []
        for c in order:
            x = [r for r in conds[c] if pred(r)]
            cells.append(f"{sum(r['correct'] for r in x)}/{len(x)}")
        print("| Correct | " + " | ".join(cells) + " |")
        cells = [str(len(per_rep(conds[c], "tool_calls", pred))) for c in order]
        print("| Repetitions | " + " | ".join(cells) + " |\n")

    print("### Trap tasks by exposure — mean per session\n")
    print("| Exposure | Condition | Trap hits | Hints | Tool calls | Cost $ | Lessons in prompt at session end |")
    print("|---|---|---|---|---|---|---|")
    for e in range(1, 6):
        for c in order:
            x = [r for r in conds[c] if r["trap_kind"] != "control" and r["exposure"] == e]
            if x:
                print(f"| {e} | {c} | {mean([r['trap_hits'] for r in x]):.2f} | {mean([r['hints'] for r in x]):.2f}"
                      f" | {mean([r['tool_calls'] for r in x]):.2f} | {mean([r['cost_usd'] for r in x]):.4f}"
                      f" | {mean([r['lessons_prompt'] for r in x]):.1f} |")


if __name__ == "__main__":
    main()
