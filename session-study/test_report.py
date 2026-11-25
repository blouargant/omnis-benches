#!/usr/bin/env python3
"""Tests for report. Run: python3 -m unittest discover -s session-study"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import report
import study

REPRO = {"runs": 5, "invalid": 0, "passed": 2, "failure_seen": 3, "status": "reproduces"}
NOPE = {"runs": 5, "invalid": 0, "passed": 5, "failure_seen": 0, "status": "does_not_reproduce"}


def cov(group, covered_by=""):
    return {"covered_by": covered_by, "group": group}


class DecideTest(unittest.TestCase):
    def test_decide(self):
        three = {"ss-1": REPRO, "ss-2": REPRO, "ss-3": REPRO, "ss-c1": {"status": "control_ok"}}
        self.assertEqual(report.decide(three, {"ss-1": cov("a"), "ss-2": cov("b"), "ss-3": cov("c")}), ("go", 3))
        self.assertEqual(report.decide(three, {"ss-1": cov("a"), "ss-2": cov("a"), "ss-3": cov("c")}), ("undecided", 2))
        two = {"ss-1": REPRO, "ss-2": REPRO, "ss-3": NOPE}
        self.assertEqual(report.decide(two, {"ss-1": cov("a"), "ss-2": cov("b", "tasks-web.json")}), ("undecided", 1))
        self.assertEqual(report.decide({"ss-1": NOPE}, {}), ("stop", 0))
        self.assertEqual(report.decide({"ss-1": REPRO}, {"ss-1": cov("a", "tasks-web.json")}), ("stop", 0))
        with self.assertRaises(ValueError) as cm:
            report.decide(three, {"ss-1": cov("a")})
        self.assertIn("ss-2", str(cm.exception))


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.tasks = os.path.join(self.out, "tasks-sessions.json")
        secret = "SECRET-SESSION-TEXT"
        turns = [{"turn_id": "s#%d" % i, "squad": "knowledge", "at": "2026-11-0%dT10:00:00Z" % (i + 1),
                  "signals": ["tool_error"] if i < 3 else [], "user_text": secret, "reply": secret,
                  "outline": secret, "next_user_text": secret} for i in range(6)]
        study.write_jsonl(os.path.join(self.out, "turns.jsonl"), turns)
        study.write_jsonl(os.path.join(self.out, "judged.jsonl"),
                          [{"turn_id": "s#0", "verdict": "failed", "reason": secret, "usage": {"total_tokens": 900}},
                           {"turn_id": "s#4", "verdict": "ok", "usage": {"total_tokens": 100}}])
        cards = [{"card": "c0%d" % (i + 1), "turn_id": "s#%d" % i, "why": "signal" if i < 3 else "control"}
                 for i in range(6)]
        study.save_json(os.path.join(self.out, "cards.json"), cards)
        study.save_json(os.path.join(self.out, "verdicts.json"),
                        {"c01": {"failure": "yes", "kind": "loop", "note": secret}, "c02": {"failure": "yes"},
                         "c03": {"failure": "no"}, "c04": {"failure": "no"}, "c05": {"failure": "unsure"},
                         "c06": {"failure": ""}})
        study.save_json(self.tasks, [
            {"id": "ss-1", "squad": "knowledge", "prompt": "Q1", "rubric": {"pass": ["a"], "failure": "loops on one search"}},
            {"id": "ss-2", "squad": "knowledge", "prompt": "Q2", "rubric": {"pass": ["a"], "failure": "answers beside the question"}},
            {"id": "ss-c1", "squad": "knowledge", "prompt": "Q3", "rubric": {"pass": ["a"], "failure": ""}}])
        self.judged = (
            [{"scenario": "ss-1", "run": i, "valid": True, "passed": False, "failure_seen": i < 3} for i in range(5)]
            + [{"scenario": "ss-2", "run": i, "valid": i < 2, "passed": True, "failure_seen": False} for i in range(5)]
            + [{"scenario": "ss-c1", "run": i, "valid": True, "passed": True, "failure_seen": False} for i in range(5)])
        study.write_jsonl(os.path.join(self.out, "run-judged.jsonl"), self.judged)
        study.write_jsonl(os.path.join(self.out, "ledger.jsonl"), [{"scenario": "ss-1", "cost": 1.25}] * 4)
        study.save_json(os.path.join(self.out, "coverage.json"),
                        {"ss-1": {"covered_by": "", "group": "search loop", "missing_signals": ["a Stop by the user"]}})

    def test_report_has_funnel_and_no_session_text(self):
        md = report.build(self.out, self.tasks)
        self.assertNotIn("SECRET-SESSION-TEXT", md)
        for label in ("Turns scanned", "Flagged", "Confirmed failures", "Scenarios", "Reproduce", "Not covered"):
            self.assertIn(label, md)
        self.assertIn("| Turns scanned | 6 |", md)
        self.assertIn("| Confirmed failures | 2 |", md)
        self.assertIn("loops on one search", md)
        self.assertIn("$5.00", md)
        self.assertIn("2026-11-01", md)
        self.assertIn("a Stop by the user", md)
        self.assertIn("**undecided**", md)

    def test_report_lists_open_cards_and_not_measured_scenarios(self):
        md = report.build(self.out, self.tasks)
        self.assertIn("c05", md)
        self.assertIn("c06", md)
        self.assertIn("not measured", md)

    def test_report_flags_failing_controls(self):
        for r in self.judged:
            if r["scenario"] == "ss-c1":
                r["passed"] = False
        study.write_jsonl(os.path.join(self.out, "run-judged.jsonl"), self.judged)
        md = report.build(self.out, self.tasks)
        self.assertIn("control fails", md)
        self.assertLess(md.index("Warning"), md.index("## Verdict"))

    def test_report_without_coverage_says_what_is_missing(self):
        os.remove(os.path.join(self.out, "coverage.json"))
        md = report.build(self.out, self.tasks)
        self.assertIn("not decided", md)
        self.assertIn("ss-1", md)

    def test_report_before_any_replay(self):
        for name in ("run-judged.jsonl", "ledger.jsonl", "coverage.json"):
            os.remove(os.path.join(self.out, name))
        md = report.build(self.out, self.tasks)
        self.assertIn("| Reproduce | 0 |", md)

    def test_scan_rows_carry_the_turn_date(self):
        sess = [{"id": "s", "squad": "k", "skills": [], "turns": [
            {"user_text": "q", "assistant_text": "a", "at": "2026-11-02T08:00:00Z",
             "tools": [{"name": "Read", "args": {}, "result": "ok"}]}]}]
        self.assertEqual(study.scan_turns(sess)[0]["at"], "2026-11-02T08:00:00Z")


if __name__ == "__main__":
    unittest.main()
