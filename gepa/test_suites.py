import json

import pytest

from gepa_omnis import suites as S


@pytest.fixture
def table(tmp_path, monkeypatch):
    bench = tmp_path / "squad-bench"
    bench.mkdir()
    (bench / "train.json").write_text(json.dumps({"tasks": [
        {"id": "t1", "squad": "system", "prompt": "a"}, {"id": "t2", "squad": "system", "prompt": "b"}]}))
    (bench / "val.json").write_text(json.dumps({"tasks": [{"id": "v1", "squad": "system", "prompt": "c"}]}))
    tbl = {
        "leader": {"squad": "system", "fake": ["summariser", "investigator"],
                   "train": ["train.json"], "val": ["val.json"], "heldout": ["val.json"]},
        "coder": {"squad": "coding", "fake": ["code_scout", "investigator"],
                  "train": ["train.json"], "val": ["val.json"], "heldout": []},
    }
    path = tmp_path / "suites.json"
    path.write_text(json.dumps(tbl))
    monkeypatch.setattr(S, "SUITES_FILE", path)
    monkeypatch.setattr(S, "BENCH_DIR", bench)
    return tbl


def test_missing_suite_lists_agents(table):
    with pytest.raises(S.MissingSuites) as e:
        S.load({"leader", "zeta", "alpha"})
    assert e.value.agents == ["alpha", "zeta"]


def test_items_train_ids_from_file(table):
    items = S.items({"leader"}, "train")
    assert [(i.agent, i.task_file, i.task_id) for i in items] == [
        ("leader", "train.json", "t1"), ("leader", "train.json", "t2")]
    assert items[0].task["prompt"] == "a"


def test_fake_union_sorted(table):
    assert S.fake_agents({"leader", "coder"}) == ["code_scout", "investigator", "summariser"]


def test_empty_heldout_refused_unless_allowed(table):
    with pytest.raises(S.MissingSuites) as e:
        S.load({"leader", "coder"})
    assert e.value.agents == ["coder"]
    assert set(S.load({"leader", "coder"}, heldout_ok_missing=["coder"])) == {"leader", "coder"}
