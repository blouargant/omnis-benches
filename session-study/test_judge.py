#!/usr/bin/env python3
"""Tests for judge. Run: python3 -m unittest discover -s session-study"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import judge

GOOD = '{"verdict":"failed","kind":"loop","reason":"same search 5 times","calls":[1,2]}'


def read(path):
    with open(path) as f:
        return [json.loads(l) for l in f]


def turn(i):
    return {"turn_id": "s#%d" % i, "user_text": "Q%d" % i, "reply": "A", "next_user_text": "", "outline": "t()"}


class TurnJudgeTest(unittest.TestCase):
    def test_turn_prompt_fences_session_text(self):
        system, user = judge.turn_prompt(turn(1))
        self.assertIn("data", system.lower())
        self.assertIn("<<<BEGIN SESSION>>>", user)
        self.assertIn("Q1", user)

    def test_turn_prompt_caps_a_huge_outline(self):
        t = turn(1)
        t["outline"] = "\n".join("call %d " % i + "x" * 500 for i in range(1000))
        _, user = judge.turn_prompt(t)
        self.assertLess(len(user), 60000)
        self.assertIn("call 0 ", user)
        self.assertIn("call 999 ", user)
        self.assertIn("lines omitted", user)

    def test_parse_turn_rejects_unknown_verdict(self):
        self.assertEqual(judge.parse_turn('{"verdict":"ok","kind":"","reason":"fine","calls":[]}')["verdict"], "ok")
        with self.assertRaises(ValueError):
            judge.parse_turn('{"verdict":"great"}')
        with self.assertRaises(ValueError):
            judge.parse_turn("sorry, I cannot")

    def test_parse_turn_fills_missing_optional_keys(self):
        self.assertEqual(judge.parse_turn('{"verdict":"wasteful"}'),
                         {"verdict": "wasteful", "kind": "", "reason": "", "calls": []})

    def test_judge_records_error_and_retries_only_errors(self):
        out = os.path.join(tempfile.mkdtemp(), "judged.jsonl")
        asked = []

        def bad_on_two(model, system, user, timeout=300):
            asked.append(user)
            return ("not json" if "Q2" in user else GOOD), {"total_tokens": 7}

        s = judge.run_judge([turn(1), turn(2), turn(3)], out, "m", call=bad_on_two)
        self.assertEqual(s, {"judged": 2, "errors": 1, "skipped": 0})
        rows = read(out)
        self.assertEqual(sorted(r["turn_id"] for r in rows), ["s#1", "s#2", "s#3"])
        self.assertIn("error", [r for r in rows if r["turn_id"] == "s#2"][0])
        self.assertEqual([r for r in rows if r["turn_id"] == "s#1"][0]["usage"], {"total_tokens": 7})

        asked.clear()
        s = judge.run_judge([turn(1), turn(2), turn(3)], out, "m", call=lambda *a, **k: (GOOD, {}))
        self.assertEqual(s, {"judged": 1, "errors": 0, "skipped": 2})
        rows = read(out)
        self.assertEqual(len(rows), 3)
        self.assertFalse(any("error" in r for r in rows))

    def test_judge_survives_a_gateway_exception(self):
        out = os.path.join(tempfile.mkdtemp(), "judged.jsonl")

        def boom(*a, **k):
            raise OSError("gateway down")

        s = judge.run_judge([turn(1)], out, "m", call=boom)
        self.assertEqual(s, {"judged": 0, "errors": 1, "skipped": 0})
        self.assertIn("gateway down", read(out)[0]["error"])


if __name__ == "__main__":
    unittest.main()
