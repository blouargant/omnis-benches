from gepa_omnis.ledger import DollarStopper, Ledger


def test_ledger_resume_keeps_total(tmp_path):
    p = tmp_path / "ledger.jsonl"
    led = Ledger(p)
    led.add(1.25, "eval")
    led.add(0.75, "reflection")
    assert Ledger(p).spent() == 2.0


def test_stopper_trips_at_ceiling(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    stop = DollarStopper(led, 1.0)
    led.add(0.99, "eval")
    assert stop(None) is False
    led.add(0.01, "eval")
    assert stop(None) is True
