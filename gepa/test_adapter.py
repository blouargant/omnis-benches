import pytest

from gepa_omnis.adapter import OmnisAdapter
from gepa_omnis.ledger import Ledger
from gepa_omnis.suites import Item
from gepa_omnis.worker import ReloadError


def rec(ok=True, **kw):
    r = {"status": "done", "quality_gate": ok, "total_cost_usd": 0.5, "answer": "a"}
    r.update(kw)
    return r


class FakeWorker:
    def __init__(self, results, fail_reload=False):
        self.results, self.applied, self.fail_reload = results, [], fail_reload

    def apply(self, cand):
        if self.fail_reload:
            raise ReloadError("boom")
        self.applied.append(cand)

    def run(self, item, repeat):
        return self.results[item.task_id].pop(0)


def items(*ids, agent="leader"):
    return [Item(agent, "f.json", i, {"id": i, "prompt": f"do {i}"}) for i in ids]


def adapter(tmp_path, workers):
    return OmnisAdapter(workers, repeat=2, ledger=Ledger(tmp_path / "l.jsonl"),
                        reach={"instruction:leader": {"leader"}, "instruction:coder": {"coder"}})


def test_evaluate_scores_in_batch_order(tmp_path):
    w1 = FakeWorker({"a": [[rec(), rec()]], "c": [[rec(False), rec(False)]]})
    w2 = FakeWorker({"b": [[rec(), rec(False)]]})
    out = adapter(tmp_path, [w1, w2]).evaluate(items("a", "b", "c"), {"instruction:leader": "x"})
    assert out.scores == [1.0, 0.5, 0.0]
    assert w1.applied == [{"instruction:leader": "x"}] == w2.applied


def test_evaluate_retries_infra_once(tmp_path):
    w = FakeWorker({"a": [[rec(status="error")], [rec()]]})
    assert adapter(tmp_path, [w]).evaluate(items("a"), {}).scores == [1.0]


def test_evaluate_infra_twice_scores_zero_and_marks(tmp_path):
    w = FakeWorker({"a": [[rec(fake_error="x")], [rec(status="error")]]})
    out = adapter(tmp_path, [w]).evaluate(items("a"), {}, capture_traces=True)
    assert out.scores == [0.0] and out.trajectories[0]["infra"] is True


def test_reflective_dataset_only_reached_agents(tmp_path):
    its = items("a") + items("k", agent="coder")
    w = FakeWorker({"a": [[rec(False)]], "k": [[rec(False)]]})
    ad = adapter(tmp_path, [w])
    batch = ad.evaluate(its, {}, capture_traces=True)
    ds = ad.make_reflective_dataset({}, batch, ["instruction:leader"])
    assert len(ds["instruction:leader"]) == 1
    assert "do a" in ds["instruction:leader"][0]["Inputs"]


def test_costs_go_to_ledger(tmp_path):
    ad = adapter(tmp_path, [FakeWorker({"a": [[rec(), rec()]]})])
    ad.evaluate(items("a"), {})
    assert ad.ledger.spent() == 1.0


def test_reload_error_propagates(tmp_path):
    with pytest.raises(ReloadError):
        adapter(tmp_path, [FakeWorker({}, fail_reload=True)]).evaluate(items("a"), {})
