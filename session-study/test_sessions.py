#!/usr/bin/env python3
"""Tests for sessions. Run: python3 -m unittest discover -s session-study"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sessions


def write(d, name, obj):
    with open(os.path.join(d, name), "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        turn = {"user_text": "q", "assistant_text": "a",
                "tools": [{"name": "Read", "args": {"file_path": "x"}, "result": {"output": "ok"}}]}
        write(self.dir, "conversation_good.json",
              {"squad": "knowledge", "skills": [{"name": "deep-research", "turn": 0}], "turns": [turn]})
        write(self.dir, "conversation_hid.json", {"hidden": True, "turns": [turn]})
        write(self.dir, "conversation_old.json", [turn])
        write(self.dir, "conversation_bad.json", "{not json")
        write(self.dir, "other.json", {})

    def test_load_skips_hidden_legacy_and_unreadable(self):
        sess, summary = sessions.load(self.dir)
        self.assertEqual([s["id"] for s in sess], ["good"])
        self.assertEqual(summary, {"files": 4, "hidden": 1, "legacy": 1, "unreadable": 1})
        self.assertEqual(sess[0]["squad"], "knowledge")
        self.assertEqual(sess[0]["skills"], [{"name": "deep-research", "turn": 0}])

    def test_load_accepts_a_file_without_turns(self):
        write(self.dir, "conversation_empty.json", {"squad": "system"})
        sess, _ = sessions.load(self.dir)
        self.assertEqual(sorted(s["id"] for s in sess), ["empty", "good"])
        self.assertEqual([s["turns"] for s in sess if s["id"] == "empty"], [[]])


class TextTest(unittest.TestCase):
    def test_text_of_survives_any_shape(self):
        self.assertEqual(sessions.text_of(None), "")
        self.assertEqual(sessions.text_of("plain"), "plain")
        self.assertIn("Error: boom", sessions.text_of({"output": "Error: boom"}))
        self.assertIn("cut", sessions.text_of('{"output": "cut'))
        self.assertIn("1", sessions.text_of([1, 2]))

    def test_strings_of_reads_values_of_dicts_and_cut_json(self):
        self.assertEqual(sessions.strings_of({"output": "Error: x", "n": 3}), ["Error: x"])
        self.assertIn("Error: no file", sessions.strings_of('{"output": "Error: no file'))
        self.assertEqual(sessions.strings_of("bare"), ["bare"])
        self.assertEqual(sessions.strings_of(None), [])

    def test_walk_yields_children_with_depth(self):
        calls = [{"name": "a", "children": [{"name": "b", "children": [{"name": "c"}]}]}, {"name": "d"}]
        self.assertEqual([(c["name"], d) for c, d in sessions.walk(calls)],
                         [("a", 0), ("b", 1), ("c", 2), ("d", 0)])

    def test_outline_nests_children_and_cuts(self):
        turn = {"tools": [{"name": "web_agent", "args": {"request": "x" * 400},
                           "children": [{"name": "WebFetch", "agent": "web_agent",
                                         "args": {"url": "https://e.x"}, "result": {"output": "ok"}}]}]}
        lines = sessions.outline(turn).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("  web_agent.WebFetch("))
        self.assertLessEqual(len(lines[0]), 700)

    def test_outline_of_a_turn_without_tools_is_empty(self):
        self.assertEqual(sessions.outline({}), "")


if __name__ == "__main__":
    unittest.main()
