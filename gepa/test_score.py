import pytest

from gepa_omnis import score as SC
from gepa_omnis.suites import Item


def rec(**kw):
    r = {"status": "done", "correct": None, "quality_gate": True, "fake_gate": None,
         "answer": "ok", "total_cost_usd": 0.01, "facts": {"missing": []},
         "forbidden_hits": [], "fake_failed": []}
    r.update(kw)
    return r


def test_passed_ignores_none_gates():
    assert SC.passed(rec())
    assert not SC.passed(rec(fake_gate=False))
    assert not SC.passed(rec(correct=False, quality_gate=True))


def test_timeout_is_fail_not_infra():
    r = rec(status="timeout")
    assert not SC.is_infra(r)
    assert not SC.passed(r)


def test_infra_records_excluded():
    assert SC.task_score([rec(), rec(status="error"), rec(fake_gate=False)]) == 0.5
    assert SC.is_infra(rec(fake_error="log gone"))


def test_all_infra_raises():
    with pytest.raises(SC.InfraError):
        SC.task_score([rec(status="error"), rec(fake_error="x")])


def test_ungradable_raises():
    with pytest.raises(ValueError):
        SC.passed(rec(quality_gate=None))


def test_feedback_has_no_patterns_or_replies():
    task = {"id": "t", "prompt": "Why is batch-09 down?",
            "facts": [{"id": "cause", "required": True, "match": "/out of memory|oom/"}],
            "forbidden": [{"id": "guess", "match": "/disk full/"}],
            "fake": {"investigator": [{"reply": "SECRET-REPLY kernel log line"}]}}
    item = Item("leader", "f.json", "t", task)
    r = rec(quality_gate=False, facts={"missing": ["cause"]}, forbidden_hits=["guess"],
            fake_gate=False, fake_failed=["investigator.max_near_repeats"],
            fake={"requests": [{"agent": "investigator", "request": "check batch-09"}]})
    text = SC.feedback(item, [r])
    assert "Why is batch-09 down?" in text
    assert "cause" in text and "investigator.max_near_repeats" in text
    for leaked in ("out of memory", "oom|", "disk full", "SECRET-REPLY"):
        assert leaked not in text
