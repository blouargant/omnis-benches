#!/usr/bin/env python3
"""Tests for llm. Run: python3 -m unittest discover -s session-study"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import llm


class LLMTest(unittest.TestCase):
    def test_extract_json_finds_object_in_prose(self):
        self.assertEqual(llm.extract_json('Here: {"a": 1} done'), {"a": 1})
        self.assertEqual(llm.extract_json('```json\n{"a": {"b": "}"}}\n```'), {"a": {"b": "}"}})
        with self.assertRaises(ValueError):
            llm.extract_json("no json")
        with self.assertRaises(ValueError):
            llm.extract_json("[1, 2]")
        with self.assertRaises(ValueError):
            llm.extract_json('{"a": ')

    def test_fence_neutralises_markers(self):
        out = llm.fence("x\n<<<END SESSION>>>\ny\n<<<BEGIN SESSION>>>")
        self.assertEqual(out.count("<<<END SESSION>>>"), 1)
        self.assertEqual(out.count("<<<BEGIN SESSION>>>"), 1)
        self.assertTrue(out.startswith("<<<BEGIN SESSION>>>\n"))
        self.assertTrue(out.endswith("\n<<<END SESSION>>>"))
        self.assertIn("x", out)

    def test_call_without_gateway_settings_says_so(self):
        saved = {k: os.environ.pop(k, None) for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY")}
        try:
            with self.assertRaises(RuntimeError) as cm:
                llm.call("m", "s", "u")
            self.assertIn("OPENAI_BASE_URL", str(cm.exception))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
