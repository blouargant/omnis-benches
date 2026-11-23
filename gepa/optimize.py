#!/usr/bin/env python3
"""Evolve omnis agent texts with GEPA against the squad-bench suites.

  optimize.py denylist  <run.json>   print the scenario names a proposal may not contain
  optimize.py calibrate <run.json>   one seed minibatch; suggests max_metric_calls
  optimize.py run       <run.json>   search, held-out check, report (resumable)

Needs `pip install -r gepa/requirements.txt` and the gateway credentials in the
environment (`set -a; . ./.env; set +a`). Nothing is written to omnis: the
report carries a patch to review and apply by hand.
"""
import argparse
import datetime
import json
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from gepa_omnis import components, guards, report, score, suites, verdict  # noqa: E402
from gepa_omnis.ledger import DollarStopper, Ledger  # noqa: E402

DEFAULTS = {"omnis_src": "../omnis", "repeat_search": 2, "repeat_heldout": 5, "workers": 2,
            "max_metric_calls": 150, "ceiling_usd": 60, "reflection_ref": "premium",
            "keep_check_ref": "hosted", "reflection_minibatch_size": 3, "seed": 0,
            "heldout_ok_missing": [], "port_base": 18900, "search_share": 0.5}


def load_config(path):
    cfg = dict(DEFAULTS, **json.loads(Path(path).read_text(encoding="utf-8")))
    for k in ("name", "omnis_ref", "components", "models"):
        if not cfg.get(k):
            raise SystemExit(f"{path}: missing {k!r}")
    src = Path(cfg["omnis_src"])
    cfg["omnis_src"] = str(src if src.is_absolute() else (HERE.parent / src).resolve())
    return cfg


def _fetch_prompts(cfg):
    """The /api/prompts catalogue of a throwaway server on the run's omnis ref,
    on the real config (no fakes): it gives prompt:<id> seeds and their reach."""
    from gepa_omnis.worker import Worker
    w = Worker(90, HERE / "out" / cfg["name"] / "work", cfg["omnis_ref"], cfg["models"][0], [], [],
               cfg["omnis_src"], port_base=cfg["port_base"])
    try:
        w.start()
        return w.prompts()
    finally:
        w.stop()


def prepare(cfg, prompts=None):
    src = Path(cfg["omnis_src"])
    if prompts is None and any(components.parse(c)[0] == "prompt" for c in cfg["components"]):
        prompts = _fetch_prompts(cfg)
    reach = {c: components.agents_reached(c, src, prompts) for c in cfg["components"]}
    agents = set().union(*reach.values())
    try:
        suites.load(agents, cfg["heldout_ok_missing"])
    except suites.MissingSuites as e:
        raise SystemExit(f"refusing to run: {e}")
    seeds = components.read_seed(src, cfg["components"], prompts)
    split = {s: suites.items(agents, s) for s in suites.SPLITS}
    deny = guards.denylist([i for s in suites.SPLITS for i in split[s]], list(seeds.values()))
    keep = {c: guards.load_keep(c) for c in cfg["components"]}
    leaders = sorted(agents)     # the agents under test run on the search model
    return {"src": src, "reach": reach, "agents": agents, "seeds": seeds, "split": split,
            "deny": deny, "keep": keep, "leaders": leaders, "fake": suites.fake_agents(agents)}


def search_ceiling(cfg):
    """The search stops here; the rest of the ceiling is kept for the held-out check."""
    return cfg["ceiling_usd"] * cfg["search_share"]


def split_heldout(items):
    """(scripted, real): tasks with a `fake` script run on fake sub-agents, the
    others on the real squad."""
    return [i for i in items if "fake" in i.task], [i for i in items if "fake" not in i.task]


def _workers(cfg, prep, workdir, model, n, fake=True, first=0):
    from gepa_omnis.worker import Worker
    return [Worker(first + i, workdir, cfg["omnis_ref"], model, prep["leaders"],
                   prep["fake"] if fake else [], prep["src"], port_base=cfg["port_base"])
            for i in range(n)]


def _start(workers):
    for w in workers:
        w.start()


def _stop(workers):
    for w in workers:
        w.stop()


def cmd_denylist(cfg):
    for w in sorted(prepare(cfg)["deny"]):
        print(w)


def cmd_calibrate(cfg):
    from gepa_omnis.adapter import OmnisAdapter
    prep = prepare(cfg)
    out = HERE / "out" / cfg["name"]
    ledger = Ledger(out / "calibrate-ledger.jsonl")
    before = ledger.spent()
    workers = _workers(cfg, prep, out / "work", cfg["models"][0], 1)
    batch = prep["split"]["train"][:cfg["reflection_minibatch_size"]]
    try:
        _start(workers)
        ad = OmnisAdapter(workers, cfg["repeat_search"], ledger, prep["reach"])
        res = ad.evaluate(batch, prep["seeds"])
    finally:
        _stop(workers)
    per_call = (ledger.spent() - before) / len(batch)
    print(f"seed scores on {len(batch)} train tasks: {res.scores}")
    print(f"cost per metric call (one task x {cfg['repeat_search']} repeats): ${per_call:.4f}")
    if per_call > 0:
        print(f"max_metric_calls fitting half of ${cfg['ceiling_usd']}: "
              f"{int(cfg['ceiling_usd'] / 2 / per_call)}")


def _heldout(adapter, items, candidate, repeat):
    adapter.repeat = repeat
    batch = adapter.evaluate(items, candidate, capture_traces=True)
    by_task = {}
    for traj in batch.trajectories:
        recs = [r for r in traj["records"] if not score.is_infra(r)]
        by_task[f"{traj['item'].task_file}:{traj['item'].task_id}"] = [score.passed(r) for r in recs]
    return by_task


def _heldout_phase(cfg, prep, out, ledger, best):
    """Seed and best on the held-out tasks, on every model: scripted tasks on
    fake sub-agents, the others on the real squad (its own workers, no fakes)."""
    from gepa_omnis.adapter import OmnisAdapter
    scripted, real = split_heldout(prep["split"]["heldout"])
    base, cand = {}, {}
    for model in cfg["models"]:
        for items, fake, first in ((scripted, True, 0), (real, False, cfg["workers"])):
            if not items:
                continue
            workers = _workers(cfg, prep, out / "work", model, cfg["workers"], fake, first)
            try:
                _start(workers)
                ad = OmnisAdapter(workers, cfg["repeat_heldout"], ledger, prep["reach"])
                ad.records_path = out / "heldout-records.jsonl"
                for agent in sorted(prep["agents"]):
                    its = [i for i in items if i.agent == agent]
                    if not its:
                        continue
                    if ledger.spent() >= cfg["ceiling_usd"]:
                        raise SystemExit(f"ceiling ${cfg['ceiling_usd']} reached during the held-out "
                                         "check; raise ceiling_usd and resume")
                    for store, c in ((base, prep["seeds"]), (cand, best)):
                        store.setdefault((agent, model), {}).update(
                            _heldout(ad, its, c, cfg["repeat_heldout"]))
            finally:
                _stop(workers)
    return base, cand


def cmd_run(cfg):
    import gepa
    from gepa_omnis import llm
    from gepa_omnis.adapter import OmnisAdapter
    from gepa_omnis.proposer import GuardedProposer

    prep = prepare(cfg)
    out = HERE / "out" / cfg["name"]
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=out / "run.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ledger = Ledger(out / "ledger.jsonl")
    reflection = llm.from_omnis(prep["src"], cfg["reflection_ref"], ledger, "reflection")
    keep_check = llm.from_omnis(prep["src"], cfg["keep_check_ref"], ledger, "keep_check")
    proposer = GuardedProposer(reflection, keep_check, prep["seeds"], prep["deny"], prep["keep"],
                               prep["reach"], out / "proposals.jsonl")
    workers = _workers(cfg, prep, out / "work", cfg["models"][0], cfg["workers"])
    try:
        _start(workers)
        adapter = OmnisAdapter(workers, cfg["repeat_search"], ledger, prep["reach"])
        adapter.records_path = out / "records.jsonl"
        result = gepa.optimize(
            seed_candidate=prep["seeds"], trainset=prep["split"]["train"], valset=prep["split"]["val"],
            adapter=adapter, reflection_lm=reflection, custom_candidate_proposer=proposer,
            frontier_type="instance", reflection_minibatch_size=cfg["reflection_minibatch_size"],
            max_metric_calls=cfg["max_metric_calls"],
            stop_callbacks=[DollarStopper(ledger, search_ceiling(cfg))],
            run_dir=str(out / "gepa"), seed=cfg["seed"])
        best = result.best_candidate
        (out / "best.json").write_text(json.dumps(best, indent=1, ensure_ascii=False), encoding="utf-8")
    finally:
        _stop(workers)
    base, cand = _heldout_phase(cfg, prep, out, ledger, best)
    decision = verdict.decide(base, cand)
    patch_text = report.patch(prep["src"], prep["seeds"], best)
    (out / "best.patch").write_text(patch_text, encoding="utf-8")
    frontier = list(enumerate(result.val_aggregate_scores))
    path = report.write(HERE.parent / "reports", cfg["name"], datetime.date.today().isoformat(),
                        cfg, prep["seeds"], best, frontier, decision, ledger.by_kind(), patch_text)
    print(f"report: {path}\npatch:  {out / 'best.patch'}\nadopt:  {decision['adopt']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["denylist", "calibrate", "run"])
    ap.add_argument("config")
    a = ap.parse_args()
    cfg = load_config(a.config)
    {"denylist": cmd_denylist, "calibrate": cmd_calibrate, "run": cmd_run}[a.command](cfg)


if __name__ == "__main__":
    main()
