from gepa_omnis import verdict as V

BASE = {"t1": [True, True, False, True, True], "t2": [False, True, False, False, True]}


def test_identical_is_same_not_adopted():
    d = V.decide({("leader", "balanced"): BASE}, {("leader", "balanced"): BASE})
    assert d["adopt"] is False and d["rows"][0]["verdict"] == "same"


def test_one_better_none_worse_adopts():
    better = {"t1": [True] * 5, "t2": [True] * 5}
    d = V.decide({("leader", "balanced"): BASE, ("leader", "premium"): better},
                 {("leader", "balanced"): better, ("leader", "premium"): better})
    assert d["adopt"] is True
    assert [r["verdict"] for r in d["rows"]] == ["better", "same"]


def test_any_worse_blocks():
    better = {"t1": [True] * 5, "t2": [True] * 5}
    worse = {"t1": [False] * 5, "t2": [False] * 5}
    d = V.decide({("leader", "balanced"): BASE, ("leader", "premium"): better},
                 {("leader", "balanced"): better, ("leader", "premium"): worse})
    assert d["adopt"] is False and d["rows"][1]["verdict"] == "worse"


def test_interval_deterministic_with_seed():
    assert V.interval(BASE) == V.interval(BASE)
    lo, hi = V.interval(BASE)
    assert lo <= V.suite_mean(BASE) <= hi
