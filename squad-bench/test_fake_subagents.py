#!/usr/bin/env python3
"""Tests for fake_subagents. Run: python3 -m unittest squad-bench/test_fake_subagents.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_subagents as fs

RULES = {"investigator": [
    {"times": 1, "reply": "off-topic", "delay_ms": 0},
    {"if_new_request": True, "reply": "good", "delay_ms": 0},
    {"reply": "off-topic again", "delay_ms": 0}]}


class TestEngine(unittest.TestCase):
    def test_reworded_request_gets_the_good_reply(self):
        s = fs.Scenario("t", RULES)
        self.assertEqual(s.answer("investigator", "why did it fail")["reply"], "off-topic")
        self.assertEqual(s.answer("investigator", "Why  did it FAIL")["reply"], "off-topic again")
        self.assertEqual(s.answer("investigator", "check the kernel log")["reply"], "good")

    def test_when_selects_by_request(self):
        s = fs.Scenario("t", {"investigator": [
            {"when": "/reports/", "reply": "B"}, {"when": "orders-sync", "reply": "A"}]})
        self.assertEqual(s.answer("investigator", "check orders-sync")["reply"], "A")
        self.assertEqual(s.answer("investigator", "who filled /var/spool/reports")["reply"], "B")

    def test_unscripted_call_gets_the_default(self):
        a = fs.Scenario("t", {}).answer("helper", "anything")
        self.assertEqual((a["reply"], a["rule"], a["delay_ms"]), ("No evidence found.", None, 300))

    def test_rule_without_delay_uses_the_default_delay(self):
        a = fs.Scenario("t", {"x": [{"reply": "r"}]}).answer("x", "q")
        self.assertEqual((a["rule"], a["delay_ms"]), (0, 300))

    def test_status_rule(self):
        a = fs.Scenario("t", {"x": [{"status": 500}]}).answer("x", "q")
        self.assertEqual((a["status"], a["reply"]), (500, None))

    def test_request_text_takes_the_last_user_message(self):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "first"},
                {"role": "assistant", "content": "a"},
                {"role": "user", "content": [{"type": "text", "text": "second "},
                                             {"type": "text", "text": "part"}]}]
        self.assertEqual(fs.request_text(msgs), "second part")
        self.assertEqual(fs.request_text([]), "")

    def test_agent_of(self):
        self.assertEqual(fs.agent_of("fake-investigator"), "investigator")
        self.assertEqual(fs.agent_of("gpt-x"), "gpt-x")

    def test_validate_script(self):
        self.assertIsNone(fs.validate_script(RULES))
        self.assertIsNotNone(fs.validate_script([]))
        self.assertIsNotNone(fs.validate_script({"a": [{"delay_ms": 1}]}))
        self.assertIsNotNone(fs.validate_script({"a": {"reply": "r"}}))


if __name__ == "__main__":
    unittest.main()
