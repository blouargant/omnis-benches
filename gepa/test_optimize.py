import json

import pytest

import optimize


def test_refuses_missing_suite(tmp_path):
    cfg = tmp_path / "run.json"
    cfg.write_text(json.dumps({"name": "k", "omnis_ref": "develop",
                               "components": ["instruction:knowledge_leader"],
                               "models": ["balanced"]}))
    with pytest.raises(SystemExit) as e:
        optimize.prepare(optimize.load_config(cfg))
    assert "knowledge_leader" in str(e.value)


def test_config_defaults(tmp_path):
    cfg = tmp_path / "run.json"
    cfg.write_text(json.dumps({"name": "x", "omnis_ref": "develop",
                               "components": ["instruction:leader"], "models": ["balanced"]}))
    c = optimize.load_config(cfg)
    assert c["repeat_search"] == 2 and c["repeat_heldout"] == 5 and c["ceiling_usd"] == 60
    assert c["reflection_ref"] == "premium" and c["keep_check_ref"] == "hosted"


def test_gepa_loop_with_stub_workers(tmp_path):
    """The real gepa.optimize drives our adapter and proposer end to end."""
    import gepa
    from gepa_omnis.adapter import OmnisAdapter
    from gepa_omnis.ledger import Ledger
    from gepa_omnis.proposer import GuardedProposer
    from gepa_omnis.suites import Item

    class W:
        text = ""

        def apply(self, cand):
            self.text = cand["instruction:leader"]

        def run(self, item, repeat):
            ok = "delegate" in self.text
            return [{"status": "done", "quality_gate": ok, "total_cost_usd": 0.01, "answer": "a"}]

    its = [Item("leader", "f.json", f"t{i}", {"id": f"t{i}", "prompt": f"q{i}"}) for i in range(4)]
    seeds = {"instruction:leader": "Coordinate the work of the squad."}
    ledger = Ledger(tmp_path / "l.jsonl")
    ad = OmnisAdapter([W()], 1, ledger, {"instruction:leader": {"leader"}})
    prop = GuardedProposer(lambda p: "```\nCoordinate; delegate first.\n```", lambda p: "YES", seeds,
                           set(), {}, {"instruction:leader": {"leader"}}, tmp_path / "p.jsonl")
    res = gepa.optimize(seed_candidate=seeds, trainset=its[:2], valset=its[2:], adapter=ad,
                        reflection_lm=lambda p: "", custom_candidate_proposer=prop,
                        frontier_type="instance", reflection_minibatch_size=2,
                        max_metric_calls=12, run_dir=str(tmp_path / "run"), seed=0)
    assert res.best_candidate["instruction:leader"] == "Coordinate; delegate first."
    assert max(res.val_aggregate_scores) == 1.0


def test_search_ceiling_reserves_heldout(tmp_path):
    cfg = tmp_path / "run.json"
    cfg.write_text(json.dumps({"name": "x", "omnis_ref": "develop", "ceiling_usd": 60,
                               "components": ["instruction:leader"], "models": ["balanced"]}))
    assert optimize.search_ceiling(optimize.load_config(cfg)) == 30


def test_split_heldout_by_script():
    from gepa_omnis.suites import Item
    its = [Item("leader", "a.json", "s", {"fake": {}}), Item("leader", "b.json", "r", {})]
    scripted, real = optimize.split_heldout(its)
    assert [i.task_id for i in scripted] == ["s"] and [i.task_id for i in real] == ["r"]


def test_prepare_takes_prompt_reach_from_catalogue(tmp_path):
    cfg = tmp_path / "run.json"
    cfg.write_text(json.dumps({"name": "p", "omnis_ref": "develop",
                               "components": ["prompt:block.choice"], "models": ["balanced"]}))
    cat = [{"id": "block.choice", "default": "Default rule.", "agents": ["leader"]}]
    prep = optimize.prepare(optimize.load_config(cfg), prompts=cat)
    assert prep["reach"] == {"prompt:block.choice": {"leader"}}
    assert prep["seeds"] == {"prompt:block.choice": "Default rule."}
