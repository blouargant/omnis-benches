"""GEPA adapter: evaluate a candidate on omnis bench workers."""
import hashlib
import subprocess
import json
import logging
import threading

from gepa.core.adapter import EvaluationBatch

from . import score

log = logging.getLogger("gepa_omnis")


class OmnisAdapter:
    propose_new_texts = None    # proposals come from GuardedProposer (custom_candidate_proposer)

    def __init__(self, workers, repeat, ledger, reach):
        self.workers, self.repeat, self.ledger, self.reach = workers, repeat, ledger, reach
        self.records_path = None       # every record is appended here when set
        self._rec_lock = threading.Lock()

    def _keep(self, tag, item, recs):
        if not self.records_path:
            return
        with self._rec_lock, open(self.records_path, "a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps({**r, "gepa_candidate": tag, "gepa_task": item.task_id,
                                    "gepa_agent": item.agent}, ensure_ascii=False) + "\n")

    def _run_item(self, worker, item):
        """(score, records, infra) — an all-infra item is run once more, then the run stops."""
        for attempt in (1, 2):
            try:
                recs = worker.run(item, self.repeat)
            except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
                log.warning("bench run failed for %s: %s", item.task_id, e)
                recs = [{"status": "error", "error": str(e)}]
            for r in recs:
                self.ledger.add(r.get("total_cost_usd") or 0.0, "eval")
            try:
                return score.task_score(recs), recs, False
            except score.InfraError:
                log.warning("infrastructure failure on %s (attempt %d)", item.task_id, attempt)
        # Twice: the bench or the gateway is down. Stop (the run resumes from its
        # last checkpoint) rather than score the candidate on a failure not its own.
        raise score.InfraError(f"task {item.task_file}:{item.task_id} failed twice for "
                               "infrastructure reasons; fix it and resume the run")

    def evaluate(self, batch, candidate, capture_traces=False):
        errors = []

        def apply(w):
            try:
                w.apply(candidate)
            except Exception as e:      # re-raised below: a candidate that did not load stops the run
                errors.append(e)

        appliers = [threading.Thread(target=apply, args=(w,)) for w in self.workers]
        for t in appliers:
            t.start()
        for t in appliers:
            t.join()
        if errors:
            raise errors[0]

        results = [None] * len(batch)
        failures = []

        def drain(wi, worker):
            try:
                for i in range(wi, len(batch), len(self.workers)):
                    results[i] = self._run_item(worker, batch[i])
            except Exception as e:      # re-raised below with its own message
                failures.append(e)

        runners = [threading.Thread(target=drain, args=(wi, w)) for wi, w in enumerate(self.workers)]
        for t in runners:
            t.start()
        for t in runners:
            t.join()
        if failures:
            raise failures[0]

        tag = hashlib.sha1(json.dumps(candidate, sort_keys=True).encode()).hexdigest()[:10]
        scores, outputs, trajs, objs = [], [], [], []
        for item, (sc, recs, infra) in zip(batch, results):
            self._keep(tag, item, recs)
            scores.append(sc)
            outputs.append(recs)
            costs = [r.get("total_cost_usd") or 0.0 for r in recs]
            objs.append({"cost": sum(costs) / max(len(costs), 1)})
            trajs.append({"item": item, "records": recs, "infra": infra})
        return EvaluationBatch(outputs=outputs, scores=scores,
                               trajectories=trajs if capture_traces else None,
                               objective_scores=objs)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        out = {}
        for name in components_to_update:
            reached = self.reach.get(name, set())
            rows = []
            for traj in eval_batch.trajectories or []:
                if traj["infra"] or traj["item"].agent not in reached:
                    continue
                item, recs = traj["item"], traj["records"]
                prompts = item.task.get("prompts") or [item.task.get("prompt", "")]
                rows.append({"Inputs": "\n".join(prompts),
                             "Generated Outputs": "\n---\n".join((r.get("answer") or "")[:1500] for r in recs),
                             "Feedback": score.feedback(item, recs)})
            out[name] = rows
        return out
