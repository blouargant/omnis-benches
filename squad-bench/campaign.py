#!/usr/bin/env python3
"""Run a time-interleaved variant campaign and record every run to JSONL.

The confound specific to a web bench is that the web moves: a page can change or
vanish mid-campaign. Running all of V0 then all of V3 would confuse web drift
with variant effect, so variants alternate within each repeat, and V0 is run
once more at the very end as a drift witness. If the closing witness diverges
from the opening one, the campaign is void — not "interesting".

The witness comparison is done PER TASK, never pooled through one median.
Pooling is blind exactly where it matters: `web-deep-ds7` declares only
OPTIONAL facts (a regex checklist cannot judge free-form research prose, so
its layer-1 gate is deliberately non-gating) and so its `quality_gate` is
unconditionally True — a pooled True/False check could never see it degrade.
And with exactly 3 witness records, a pooled cost median picks the
middle-ranked value, which is immune to a blow-up in whichever single record
is already the cost outlier — almost always the deep task. So `drift_ok` keys
both witness passes by task id and checks each task against itself: a quality
regression (True -> False) where a task can fail it, an observation-count
collapse (`facts.optional_found`) where it can't, and a per-task cost blow-up.

A second, independent confound is the search backend itself: a run made while
search is failing (rate-limited, timing out, returning nothing) looks both
expensive and low-quality regardless of the variant's merits. Rather than a
pre-flight probe (the fleet now runs on a paid Serper backend, so probing e.g.
DuckDuckGo would measure the wrong thing), every completed record is inspected
POST-HOC and flagged `search_degraded` when its `subagent_errors` carry a
search-failure marker or its `fetches` count is anomalous versus its peers
running the same task under the same variant in this campaign. Degraded runs
are kept in the output (nothing is thrown away) but excluded from the
end-of-campaign medians.

A third fact this file designs around: two runs of the IDENTICAL configuration
were observed to differ by 1.85x in cost ($0.908 vs $1.682) and 1.5x in
fetches. A median alone hides that spread, and a difference between variants
smaller than the spread means nothing — so the end-of-campaign summary always
prints the min-max range and the run count beside every median.

Usage:
  set -a; . ./.env; set +a
  python3 squad-bench/campaign.py --variants V0,V1,V3,V3b --repeat 2 \
      --tasks squad-bench/tasks-web.json --out campaign.jsonl
"""
import argparse
import copy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench       # noqa: E402
import variants    # noqa: E402

COST_DRIFT_FACTOR = 2.0   # witness cost may not more than double

# ----------------------------------------------------------------------------- ordering / stats

def interleaved_order(variant_ids, repeats):
    """[V0,V1,V3, V0,V1,V3, ...] — variants alternate, so web drift and gateway
    weather hit every variant equally instead of only the ones run last."""
    order = []
    for _ in range(max(0, repeats)):
        order.extend(variant_ids)
    return order


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def spread(records, key="total_cost_usd"):
    """median + min/max + count for one numeric field across records
    (None-safe). Two runs of the IDENTICAL config were observed to differ
    1.85x in cost -- a median alone hides that; this is what makes the range
    visible everywhere a median is reported."""
    xs = [r.get(key) for r in records if r.get(key) is not None]
    return {
        "median": median(xs),
        "min": min(xs) if xs else None,
        "max": max(xs) if xs else None,
        "n": len(xs),
    }


# A closing witness's observation count dropping to less than half the
# opening one's voids the campaign on a NON-GATING task (one with no required
# facts, so `quality_gate` can never itself go False -- web-deep-ds7 is the
# shipped example). This is a MEASURED threshold, not a guess: on that exact
# task a healthy answer set yields 5 `facts.optional_found` observations,
# while three separately captured degraded-search runs yielded 1, 2, and 3
# (see tasks-web.json's web-deep-ds7 notes -- "calib run1/run2/run3"). A >2x
# drop cleanly separates "healthy" (5) from every observed degraded sample
# (1-3), with margin.
OBSERVATION_DROP_FACTOR = 2.0


def _optional_found_count(record):
    return len((record.get("facts") or {}).get("optional_found") or [])


def _index_by_task(records):
    """Last-write-wins map of task id -> record. A witness pass runs each
    task exactly once, so collisions aren't expected; last-write-wins is a
    safe, simple default if one is ever declared twice."""
    return {r.get("task"): r for r in records if r.get("task") is not None}


def drift_ok(first, last):
    """Compare the opening and closing V0 witness runs, PER TASK.

    Every task gets the SAME three checks -- quality regression, observation
    collapse, cost blow-up -- there is no separate 'gated task' vs
    'non-gating task' code path, because that split can be read straight off
    each task's own numbers: a task with required facts can flip
    `quality_gate` True->False (web-lookup, web-canary); a task with only
    optional facts never can (web-deep-ds7's `quality_gate` is unconditionally
    True by construction), so for it the observation-count check is what
    carries the signal instead. Applying both quality-side checks to every
    task uniformly means neither needs to know which kind of task it is, and
    the one that doesn't apply to a given task is simply a no-op for it (e.g.
    web-lookup declares no optional facts, so its counts are 0 vs 0 and the
    collapse check never fires). The cost check applies to every task
    unconditionally, independent of which quality signal fires for it.

    A task present in only one of the two witness passes is skipped (no
    signal to compare) rather than raising."""
    if not first or not last:
        return True, "no witness pair"
    opened, closed = _index_by_task(first), _index_by_task(last)
    for task, was in opened.items():
        now = closed.get(task)
        if now is None:
            continue
        if was.get("quality_gate") is True and now.get("quality_gate") is False:
            return False, (f"baseline quality regressed on {task} between the "
                           "opening and closing witness")
        oc, cc = _optional_found_count(was), _optional_found_count(now)
        if oc > 0 and cc < oc / OBSERVATION_DROP_FACTOR:
            return False, (f"baseline observation count collapsed on {task}: "
                           f"{oc} -> {cc} optional facts found "
                           f"(> {OBSERVATION_DROP_FACTOR}x drop)")
        c0, c1 = was.get("total_cost_usd"), now.get("total_cost_usd")
        if c0 and c1 and c1 > c0 * COST_DRIFT_FACTOR:
            return False, (f"baseline cost drifted on {task}: {c0} -> {c1} "
                           f"(> {COST_DRIFT_FACTOR}x)")
    return True, "stable"


# ----------------------------------------------------------------------------- search-degradation detector
#
# Post-hoc, not pre-flight: instead of probing a search backend before the
# campaign runs (which only tells you the backend was reachable a moment
# ago, and measures the wrong thing once the fleet is behind a paid Serper
# gateway rather than DuckDuckGo), every completed record is inspected after
# the fact. Backend-agnostic and needs no extra credentials.

SEARCH_DEGRADED_MARKERS = (
    "deadline exceeded",
    "timeout",
    "non-functional",
    "rate limit",
    "429",
    "no results",
)

# How far a record's `fetches` may sit from its same-task/same-variant peers'
# median before it is judged anomalous rather than ordinary run-to-run
# variance. Calibrated above the measured 1.5x spread between two
# identical-config runs, so normal noise never trips it.
FETCH_ANOMALY_FACTOR = 3.0

# The peer group's median `fetches` must be at least this large before the
# ratio test above is allowed to fire at all. A real campaign flagged three
# `web-lookup` runs as anomalous with reasons `fetches=3 vs peer median 0.5`,
# `fetches=0 vs peer median 1.0`, and `fetches=0 vs peer median 2.0` -- on a
# task that legitimately makes 0-3 fetches, a swing of one or two fetches
# produces an enormous ratio, and a "peer median" under 1 isn't a meaningful
# quantity to divide by in the first place. 5 is chosen because every
# observed false-positive peer median (0.5, 1.0, 2.0) sits well under it,
# while the one confirmed genuine anomaly on record (21 fetches vs a peer
# median of 108) sits two orders of magnitude above it -- there is a wide gap
# between "noise on a low-fetch task" and "a real collapse/explosion on a
# high-fetch task" for this floor to sit inside. Below the floor, only the
# (volume-independent) subagent_errors signal can flag a run -- a search
# backend failing is real regardless of how few fetches were attempted.
FETCH_ANOMALY_MIN_PEER_MEDIAN = 5


def _error_markers(record):
    """Search-failure substrings found in this record's subagent_errors detail
    text, case-insensitive, deduplicated. Empty == no marker hit."""
    hits = set()
    for e in record.get("subagent_errors") or []:
        detail = str((e or {}).get("detail", "")).lower()
        hits.update(marker for marker in SEARCH_DEGRADED_MARKERS if marker in detail)
    return sorted(hits)


def _fetch_peers(record, campaign_records):
    """Other records' fetch counts for the SAME task AND SAME variant in
    this campaign.

    Fetch counts are only comparable within one task — a lookup task
    legitimately fetches far less than a deep multi-turn one. Just as
    important: they are only comparable within one VARIANT. A variant that
    fetches far fewer times BY DESIGN (e.g. V3 delegates fetching to a
    one-step sub-agent specifically to collapse an F^2 term) is not
    degraded — it is doing exactly its job — so comparing it against a
    different variant's count would flag the very effect a campaign exists
    to measure as if it were a backend failure. 'anomalous versus the other
    records in the same campaign' is therefore read as 'in the same
    campaign, for the same task and the same variant'."""
    task, variant = record.get("task"), record.get("variant")
    return [r.get("fetches") for r in campaign_records
            if r is not record and r.get("task") == task and r.get("variant") == variant
            and r.get("fetches") is not None]


def fetches_anomalous(record, campaign_records, factor=FETCH_ANOMALY_FACTOR,
                       min_peer_median=FETCH_ANOMALY_MIN_PEER_MEDIAN):
    """True when `record`'s fetch count is more than `factor`x away (either
    direction) from the median of its same-task/same-variant peers. Needs at
    least 2 peers to judge against; with fewer it never flags (nothing to
    compare) — in practice this means a variant needs `--repeat >= 3` (or is
    V0, witnessed 3x by construction) before its own fetch count can be
    judged anomalous against itself.

    The ratio test additionally requires the peer median itself to be at
    least `min_peer_median` — below that floor a peer median is too small a
    sample of real search activity for a ratio to mean anything (see
    FETCH_ANOMALY_MIN_PEER_MEDIAN), so a low-volume task (0-3 fetches is
    normal) never gets flagged on fetch count alone. This subsumes the old
    "peer median is exactly 0" special case, since 0 is always below any
    positive floor."""
    fetches = record.get("fetches")
    if fetches is None:
        return False
    peers = _fetch_peers(record, campaign_records)
    if len(peers) < 2:
        return False
    m = median(peers)
    if not m or m < min_peer_median:
        return False
    return fetches > m * factor or fetches < m / factor


def mark_search_degraded(record, campaign_records):
    """Inspect one completed record and set `search_degraded` (bool) +
    `degraded_reason` (str, empty when clean) on it, in place. Returns the
    record for convenience.

    Flags degraded when either: `subagent_errors` contain a search-failure
    marker, or `fetches` is anomalous versus same-task/same-variant peers in
    `campaign_records`. A degraded run looks both expensive and low-quality
    regardless of the variant's merits, so it must be identifiable after the
    fact and excluded from medians."""
    reasons = []
    hits = _error_markers(record)
    if hits:
        reasons.append("subagent_errors: " + ", ".join(hits))
    if fetches_anomalous(record, campaign_records):
        peers = _fetch_peers(record, campaign_records)
        reasons.append(f"fetches={record.get('fetches')} vs peer median {median(peers)}"
                       f" ({record.get('variant')}/{record.get('task')})")
    record["search_degraded"] = bool(reasons)
    record["degraded_reason"] = "; ".join(reasons)
    return record


# ----------------------------------------------------------------------------- end-of-campaign summary

def campaign_summary(records, key="total_cost_usd"):
    """Per-variant {median, min, max, n, total, excluded} for `key`, in
    first-seen variant order. Records are grouped by `variant` across EVERY
    phase (witness-open / campaign / witness-close) -- V0's witness runs
    contribute to its own baseline statistics rather than being silently
    dropped from the summary. Records lacking a `variant` are ignored.
    `search_degraded` records are excluded from median/min/max (`n`,
    `total_cost_usd`-bearing count) but still counted in `total`, so the
    exclusion itself stays visible rather than silently shrinking `n`."""
    order, groups = [], {}
    for r in records:
        v = r.get("variant")
        if v is None:
            continue
        if v not in groups:
            groups[v] = []
            order.append(v)
        groups[v].append(r)
    out = []
    for v in order:
        recs = groups[v]
        clean = [r for r in recs if not r.get("search_degraded")]
        s = spread(clean, key)
        s["total"] = len(recs)
        s["excluded"] = len(recs) - len(clean)
        out.append((v, s))
    return out


def ranges_overlap(a, b):
    """True when two spread() dicts' [min, max] ranges intersect."""
    if a["min"] is None or b["min"] is None:
        return False
    return a["min"] <= b["max"] and b["min"] <= a["max"]


def print_campaign_summary(records, baseline_id="V0"):
    """Per-variant median cost, its min-max range, and the run count -- never
    a bare 'variant X is N% cheaper' without the range beside it. A
    comparison against `baseline_id`'s median is only ever printed alongside
    both ranges and a note on whether they overlap (an overlap means the
    difference is smaller than the observed spread and is not, by itself,
    evidence of anything)."""
    print("\n===== campaign cost summary (median + range; search-degraded runs excluded) =====")
    summary = campaign_summary(records)
    by_id = dict(summary)
    baseline = by_id.get(baseline_id)
    for vid, s in summary:
        excl = f"  [{s['excluded']} excluded: search-degraded]" if s["excluded"] else ""
        if s["n"] == 0:
            print(f"  {vid:<6} n=0/{s['total']}{excl}  -- no clean runs to summarize")
            continue
        line = (f"  {vid:<6} n={s['n']}/{s['total']}{excl}"
                f"  median=${s['median']:.3f}  range=${s['min']:.3f}-${s['max']:.3f}")
        if baseline is not None and vid != baseline_id and baseline["n"] and baseline["median"]:
            pct = (s["median"] - baseline["median"]) / baseline["median"] * 100
            note = ("ranges overlap baseline — not distinguishable from noise"
                    if ranges_overlap(baseline, s) else "ranges do not overlap baseline")
            line += f"   ({pct:+.0f}% vs {baseline_id} median, {note})"
        print(line)


# ----------------------------------------------------------------------------- run one task

def _run(base, token, task, agents, deadline, out, vid, phase):
    m = bench.run_task(base, token, copy.deepcopy(task), agents, deadline, False, None)
    m["variant"] = vid
    m["phase"] = phase
    m["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    bench.summarize(m)
    if out:
        with open(out, "a") as f:
            f.write(json.dumps(m) + "\n")
    return m


def main():
    ap = argparse.ArgumentParser(description="Interleaved variant campaign.")
    ap.add_argument("--server", default=os.environ.get("OMNIS_SERVER", "http://127.0.0.1:8080"))
    ap.add_argument("--token", default=os.environ.get("OMNIS_SERVER_TOKEN", ""))
    ap.add_argument("--tasks", default=os.path.join(HERE, "tasks-web.json"))
    ap.add_argument("--variants-file", default=os.path.join(HERE, "variants.json"))
    ap.add_argument("--variants", default="V0", help="comma-separated variant ids")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--deadline", type=int, default=420, help="per-turn cap (s)")
    ap.add_argument("--out", help="append one JSON record per run")
    args = ap.parse_args()

    with open(args.tasks) as f:
        tasks = json.load(f)["tasks"]
    catalog = variants.load_variants(args.variants_file)
    ids = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in ids if v not in catalog]
    if unknown:
        sys.exit(f"unknown variant(s): {', '.join(unknown)}")

    # Snapshot whatever --out already held (e.g. an earlier campaign
    # invocation) BEFORE this run appends anything, so the end-of-campaign
    # rewrite below (which needs to add the search_degraded verdict to every
    # record of THIS run) can restore it verbatim instead of clobbering it.
    preexisting_out = ""
    if args.out and os.path.exists(args.out):
        with open(args.out) as f:
            preexisting_out = f.read()

    squads = bench.api("GET", args.server, "/api/squads", args.token)
    agents = set()
    for s in squads.get("squads", []):
        agents.update(s.get("members", []))
        if s.get("leader"):
            agents.add(s["leader"])

    sw = variants.Switcher(args.server, args.token)
    sw.snapshot()
    opening, closing = [], []
    all_records = []
    revert_mismatch = None
    try:
        print("=== opening witness (V0) ===")
        sw.apply(catalog["V0"])
        for t in tasks:
            r = _run(args.server, args.token, t, agents,
                     args.deadline, args.out, "V0", "witness-open")
            opening.append(r)
            all_records.append(r)

        for vid in interleaved_order(ids, args.repeat):
            v = catalog[vid]
            sw.apply(v)
            bad = sw.verify(v)
            if bad:
                sys.exit(f"variant {vid} did not apply cleanly: {bad}")
            print(f"=== {vid} — {v['label']} ===")
            for t in tasks:
                r = _run(args.server, args.token, t, agents, args.deadline, args.out, vid, "campaign")
                all_records.append(r)

        print("=== closing witness (V0) ===")
        sw.apply(catalog["V0"])
        for t in tasks:
            r = _run(args.server, args.token, t, agents,
                     args.deadline, args.out, "V0", "witness-close")
            closing.append(r)
            all_records.append(r)
    finally:
        revert_mismatch = sw.revert()
        print("revert:", "clean" if not revert_mismatch else f"MISMATCH {revert_mismatch}")

    # Post-hoc degradation pass: needs every record in the campaign as peer
    # context (a run early in the campaign has no same-task/same-variant
    # peers yet while the campaign is still in flight), so it runs once,
    # here, over the complete set -- then THIS run's slice of --out is
    # rewritten in full (any content that pre-dated this invocation is
    # restored verbatim) so the on-disk records carry the same verdict the
    # printed summary uses.
    # (The incremental per-run appends above are the crash-resilience copy;
    # this is the authoritative, fully-annotated one written on a normal
    # completion.)
    for r in all_records:
        mark_search_degraded(r, all_records)
    if args.out:
        with open(args.out, "w") as f:
            f.write(preexisting_out)
            for r in all_records:
                f.write(json.dumps(r) + "\n")

    print_campaign_summary(all_records)

    ok, why = drift_ok(opening, closing)
    print(f"\n===== drift witness: {'OK' if ok else 'CAMPAIGN VOID'} — {why} =====")

    # A failed revert must never report success: it leaves the server
    # misconfigured for whatever runs next, silently, unless the exit code
    # says so. Checked (and exits) AFTER the drift line above so the operator
    # sees both -- but the revert failure wins the exit code (a distinct,
    # non-drift-void code) since a misconfigured server is the more urgent
    # problem for whatever is queued behind this campaign.
    if revert_mismatch:
        print(f"\n===== REVERT FAILED — server config left MISMATCHED, "
              f"do not trust it: {revert_mismatch} =====")
        sys.exit(3)

    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
