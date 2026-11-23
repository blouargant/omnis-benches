"""Held-out verdict: is the candidate better than the baseline beyond noise?"""
import random


def suite_mean(recs_by_task):
    fracs = [sum(v) / len(v) for v in recs_by_task.values() if v]
    return sum(fracs) / len(fracs) if fracs else 0.0


def interval(recs_by_task, level=0.90, n=2000, seed=0):
    """Bootstrap interval of the suite mean, resampling repeats within each task."""
    rng = random.Random(seed)
    tasks = [v for v in recs_by_task.values() if v]
    means = sorted(
        sum(sum(rng.choice(v) for _ in v) / len(v) for v in tasks) / len(tasks)
        for _ in range(n))
    cut = (1 - level) / 2
    return means[int(cut * n)], means[min(int((1 - cut) * n), n - 1)]


def decide(base, cand):
    rows = []
    for key in sorted(base):
        agent, model = key
        lo, hi = interval(base[key])
        m = suite_mean(cand[key])
        rows.append({"agent": agent, "model": model, "base_mean": round(suite_mean(base[key]), 3),
                     "base_lo": round(lo, 3), "base_hi": round(hi, 3), "cand_mean": round(m, 3),
                     "verdict": "better" if m > hi else "worse" if m < lo else "same"})
    verdicts = [r["verdict"] for r in rows]
    return {"adopt": "worse" not in verdicts and "better" in verdicts, "rows": rows}
