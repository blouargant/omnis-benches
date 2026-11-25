#!/usr/bin/env python3
"""Tests for signals. Run: python3 -m unittest discover -s session-study"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import signals


def turn(results=(), reply="A fine answer.", calls=None):
    tools = calls if calls is not None else [
        {"name": "Bash", "args": {"command": "c%d" % i}, "result": r} for i, r in enumerate(results)]
    return {"user_text": "q", "assistant_text": reply, "tools": tools}


def sig(t, nxt="", p90=100.0):
    return signals.for_turn(t, nxt, p90)


class SignalsTest(unittest.TestCase):
    def test_tool_error(self):
        self.assertIn("tool_error", sig(turn([{"output": "Error: no such file"}])))
        self.assertIn("tool_error", sig(turn([{"error": "x"}])))
        self.assertIn("tool_error", sig(turn(['{"output": "error fetching URL: HTTP 403'])))
        self.assertNotIn("tool_error", sig(turn([{"output": "Errors in 3 files", "error": ""}])))
        self.assertNotIn("tool_error", sig(turn([{"output": "ErrorHandler is defined"}])))

    def test_blocked(self):
        for text in ("[BLOCKED BY HOOK] Bash: no", "[BLOCKED BY AUTO MODE] out of scope", "[DENIED] by the user"):
            self.assertIn("blocked", sig(turn([{"output": text}])), text)

    def test_halted(self):
        for text in ("[BUDGET REACHED] The user stopped further research",
                     "[TOOL BUDGET REACHED] conclude", "[CALL BUDGET REACHED] You have used all 20"):
            self.assertIn("halted", sig(turn([{"output": text}])), text)
        self.assertNotIn("halted", sig(turn([{"output": "ok", "call_budget": "[CALL BUDGET] 3 tool call(s) left"}])))

    def test_empty_subagent(self):
        t = turn([{"result": "(The sub-agent stopped without writing a result. Its findings are lost"}])
        self.assertIn("empty_subagent", sig(t))

    def test_repeated_call(self):
        same = {"name": "WebSearch", "args": {"query": "x"}, "result": {"results": []}}
        self.assertIn("repeated_call", sig(turn(calls=[dict(same), dict(same), dict(same)])))
        self.assertNotIn("repeated_call", sig(turn(calls=[dict(same), dict(same)])))
        nested = [{"name": "web_agent", "args": {"request": "r"}, "children": [dict(same), dict(same), dict(same)]}]
        self.assertIn("repeated_call", sig(turn(calls=nested)))

    def test_many_calls(self):
        self.assertIn("many_calls", sig(turn([{"output": "ok"}] * 11), p90=10))
        self.assertNotIn("many_calls", sig(turn([{"output": "ok"}] * 10), p90=10))

    def test_reply_cut_and_empty(self):
        self.assertIn("reply_cut", sig(turn([{"output": "ok"}], reply="text\n[Reply cut: the model")))
        self.assertIn("empty_reply", sig(turn([{"output": "ok"}], reply="  ")))

    def test_user_pushback(self):
        t = turn([{"output": "ok"}])
        for nxt in ("Non, ce n'est pas ça", "No, that's wrong", "  toujours pas bon", "Ça ne marche pas"):
            self.assertIn("user_pushback", sig(t, nxt), nxt)
        for nxt in ("Merci", "", "Note that it works", "Nonobstant cela, continue", "Pascal est d'accord"):
            self.assertNotIn("user_pushback", sig(t, nxt), nxt)

    def test_clean_turn_has_no_signal(self):
        self.assertEqual(sig(turn([{"output": "ok"}, "plain result", None])), [])

    def test_p90(self):
        self.assertEqual(signals.p90([]), 0.0)
        self.assertEqual(signals.p90([5]), 5.0)
        self.assertEqual(signals.p90(list(range(1, 11))), 9.0)


if __name__ == "__main__":
    unittest.main()
