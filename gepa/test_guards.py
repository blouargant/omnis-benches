from gepa_omnis import guards as G
from gepa_omnis.suites import Item


def item(prompt, reply="", match="/x/"):
    return Item("leader", "f.json", "t", {
        "id": "t", "prompt": prompt,
        "fake": {"investigator": [{"reply": reply}]},
        "facts": [{"id": "cause", "required": True, "match": match}]})


def test_denylist_catches_scripted_host():
    deny = G.denylist([item("Host `relay-07` runs `mailgate`.", "see /var/log/smtpd.log:2291",
                            "/certificate.{0,80}expired|revoked/")], seeds=[])
    for word in ("relay-07", "mailgate", "/var/log/smtpd.log:2291"):
        assert word in deny, word
    assert "certificate" not in deny and "expired" not in deny


def test_denylist_skips_seed_words():
    deny = G.denylist([item("Ask the `investigator` about `relay-07`.")],
                      seeds=["Delegate to the investigator."])
    assert "investigator" not in deny
    assert "relay-07" in deny


def test_leak_whole_word_only():
    deny = {"relay-07", "mailgate"}
    assert G.leaks("Check RELAY-07 first.", deny) == ["relay-07"]
    assert G.leaks("mailgates and relay-071", deny) == []


def test_too_long_ratio():
    assert not G.too_long("a" * 130, "a" * 100)
    assert G.too_long("a" * 131, "a" * 100)


def test_dropped_rules_uses_whole_candidate():
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return "YES"

    cand = {"instruction:leader": "Coordinate.", "turn_reminder:leader": "Stop after two tries."}
    assert G.dropped_rules(cand, ["Stop after two unhelpful attempts."], ask) == []
    assert "Stop after two tries." in seen[0] and "Coordinate." in seen[0]


def test_dropped_rule_reported():
    rules = ["Always end with a written answer.", "Two questions = two calls."]
    answers = iter(["NO, it is gone", "yes"])
    assert G.dropped_rules({"x:y": "t"}, rules, lambda p: next(answers)) == [rules[0]]

