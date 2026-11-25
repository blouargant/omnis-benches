#!/usr/bin/env python3
"""Tests for review. Run: python3 -m unittest discover -s session-study"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import review
import study


def turn(i, signals=()):
    return {"turn_id": "s#%d" % i, "squad": "knowledge", "signals": list(signals), "user_text": "Question %d" % i,
            "reply": "Reply %d" % i, "next_user_text": "", "outline": "Read(x) -> ok"}


def fixture():
    turns = [turn(i) for i in range(20)]
    for i in (0, 1, 2):
        turns[i]["signals"] = ["repeated_call"]
    judged = {"s#2": {"turn_id": "s#2", "verdict": "failed"}, "s#3": {"turn_id": "s#3", "verdict": "wasteful"},
              "s#4": {"turn_id": "s#4", "verdict": "ok"}, "s#5": {"turn_id": "s#5", "error": "x"}}
    return turns, judged


class PickTest(unittest.TestCase):
    def test_pick_takes_every_candidate_and_eight_controls(self):
        turns, judged = fixture()
        cards = review.pick(turns, judged)
        self.assertEqual(len(cards), 12)
        self.assertEqual(sum(c["why"] == "control" for c in cards), 8)
        why = {c["turn_id"]: c["why"] for c in cards}
        self.assertEqual((why["s#0"], why["s#2"], why["s#3"]), ("signal", "both", "judge"))
        self.assertEqual([c["card"] for c in cards], ["c%02d" % i for i in range(1, 13)])

    def test_pick_is_shuffled_and_repeatable(self):
        turns, judged = fixture()
        a, b = review.pick(turns, judged), review.pick(turns, judged)
        self.assertEqual(a, b)
        self.assertNotEqual([c["why"] for c in a][:4], ["signal", "signal", "both", "judge"])

    def test_pick_with_fewer_clean_turns_than_controls(self):
        turns = [turn(0, ["tool_error"])] + [turn(i) for i in (1, 2, 3)]
        cards = review.pick(turns, {})
        self.assertEqual(sum(c["why"] == "control" for c in cards), 3)


class CardTest(unittest.TestCase):
    def test_card_hides_signals_and_verdict(self):
        md = review.card_markdown("c01", turn(1, ["repeated_call", "many_calls"]))
        for word in ("repeated_call", "many_calls", "wasteful", "control", "signal"):
            self.assertNotIn(word, md)
        for part in ("c01", "Question 1", "Read(x) -> ok", "Reply 1"):
            self.assertIn(part, md)

    def test_long_reply_shows_head_and_tail(self):
        t = turn(1)
        t["reply"] = "HEAD" + "a" * 2000 + "MIDDLE" + "b" * 2000 + "TAIL"
        md = review.card_markdown("c01", t)
        self.assertIn("HEAD", md)
        self.assertIn("TAIL", md)
        self.assertNotIn("MIDDLE", md)

    def test_short_reply_is_shown_whole(self):
        t = turn(1)
        t["reply"] = "x" * 1100 + "END"
        self.assertIn("x" * 1100 + "END", review.card_markdown("c01", t))


class VerdictsTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def test_read_verdicts_separates_open_and_invalid(self):
        path = os.path.join(self.out, "verdicts.json")
        with open(path, "w") as f:
            json.dump({"c01": {"failure": "YES ", "kind": "loop"}, "c02": {"failure": ""},
                       "c03": {"failure": "maybe"}, "c04": {"failure": "unsure"}, "c05": {"failure": "no"},
                       "c06": "yes"}, f)
        valid, open_ = review.read_verdicts(path)
        self.assertEqual(set(valid), {"c01", "c05"})
        self.assertEqual(valid["c01"], {"failure": "yes", "kind": "loop", "note": ""})
        self.assertEqual(set(open_), {"c02", "c03", "c04", "c06"})

    def test_read_verdicts_without_a_file(self):
        self.assertEqual(review.read_verdicts(os.path.join(self.out, "none.json")), ({}, []))

    def test_review_does_not_overwrite_verdicts(self):
        turns, judged = fixture()
        study.write_jsonl(os.path.join(self.out, "turns.jsonl"), turns)
        study.write_jsonl(os.path.join(self.out, "judged.jsonl"), list(judged.values()))
        study.main(["--out", self.out, "review"])
        path = os.path.join(self.out, "verdicts.json")
        with open(path) as f:
            v = json.load(f)
        self.assertEqual(len(v), 12)
        self.assertEqual(v["c01"], {"failure": "", "kind": "", "note": ""})
        v["c01"]["failure"] = "yes"
        with open(path, "w") as f:
            json.dump(v, f)
        study.main(["--out", self.out, "review"])
        with open(path) as f:
            self.assertEqual(json.load(f)["c01"]["failure"], "yes")
        with open(os.path.join(self.out, "review.md")) as f:
            self.assertEqual(f.read().count("\n## c"), 12)

    def test_cards_are_frozen_once_verdicts_exist(self):
        # a later judge run must not renumber the cards under the user's answers
        turns, judged = fixture()
        study.write_jsonl(os.path.join(self.out, "turns.jsonl"), turns)
        study.write_jsonl(os.path.join(self.out, "judged.jsonl"), list(judged.values()))
        study.main(["--out", self.out, "review"])
        with open(os.path.join(self.out, "cards.json")) as f:
            before = json.load(f)
        judged["s#9"] = {"turn_id": "s#9", "verdict": "failed"}
        judged["s#10"] = {"turn_id": "s#10", "verdict": "failed"}
        study.write_jsonl(os.path.join(self.out, "judged.jsonl"), list(judged.values()))
        study.main(["--out", self.out, "review"])
        with open(os.path.join(self.out, "cards.json")) as f:
            self.assertEqual(json.load(f), before)

    def test_precision_counts(self):
        turns = [turn(i, ["tool_error"]) for i in range(4)] + [turn(4), turn(5)]
        judged = {"s#0": {"verdict": "failed"}, "s#4": {"verdict": "wasteful"}}
        cards = [{"card": "c%02d" % (i + 1), "turn_id": "s#%d" % i, "why": w}
                 for i, w in enumerate(["both", "signal", "signal", "signal", "judge", "control"])]
        verdicts = {"c01": {"failure": "yes"}, "c02": {"failure": "yes"}, "c03": {"failure": "no"},
                    "c05": {"failure": "no"}, "c06": {"failure": "yes"}}
        p = review.precision(cards, verdicts, {t["turn_id"]: t for t in turns}, judged)
        self.assertEqual(p["rows"]["tool_error"], {"flagged": 4, "checked": 3, "real": 2, "precision": 2 / 3})
        self.assertEqual(p["rows"]["judge"], {"flagged": 2, "checked": 2, "real": 1, "precision": 0.5})
        self.assertEqual((p["controls_checked"], p["controls_real"]), (1, 1))

    def test_a_card_whose_session_was_deleted_is_ignored(self):
        # the user deleted a session, then ran `scan` again: its card has no turn any more
        t = turn(0, ["halted"])
        cards = [{"card": "c01", "turn_id": "s#0", "why": "signal"}, {"card": "c02", "turn_id": "gone#3", "why": "signal"}]
        verdicts = {"c01": {"failure": "yes"}, "c02": {"failure": "yes"}}
        p = review.precision(cards, verdicts, {"s#0": t}, {})
        self.assertEqual(p["rows"]["halted"], {"flagged": 1, "checked": 1, "real": 1, "precision": 1.0})
        study.write_jsonl(os.path.join(self.out, "turns.jsonl"), [t])
        study.save_json(os.path.join(self.out, "cards.json"), cards)
        study.save_json(os.path.join(self.out, "verdicts.json"), verdicts)
        study.main(["--out", self.out, "review"])
        with open(os.path.join(self.out, "review.md")) as f:
            self.assertEqual(f.read().count("\n## c"), 1)

    def test_precision_with_nothing_checked(self):
        t = turn(0, ["halted"])
        p = review.precision([{"card": "c01", "turn_id": "s#0", "why": "signal"}], {}, {"s#0": t}, {})
        self.assertEqual(p["rows"]["halted"], {"flagged": 1, "checked": 0, "real": 0, "precision": None})


if __name__ == "__main__":
    unittest.main()
