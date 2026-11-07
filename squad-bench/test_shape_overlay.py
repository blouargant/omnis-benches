#!/usr/bin/env python3
"""Tests for shape_overlay. Run: python3 -m unittest squad-bench/test_shape_overlay.py"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import shape_overlay

INSTRUCTION = "You are Coder.\n\n- **Scout** (`code_scout`) — navigator.\n"


def fake_sys(d: Path) -> Path:
    (d / "registry/agents/coder").mkdir(parents=True)
    (d / "agents.json").write_text(json.dumps({"agents": ["coder"], "squads": [
        {"name": "Coding", "leader": "coder", "members": ["code_scout", "code_docs", "reviewer"]}]}))
    (d / "registry/agents/coder/agent.json").write_text(json.dumps(
        {"name": "coder", "tools": ["fs", "lsp", "web"], "leader": True}))
    (d / "registry/agents/coder/instruction.md").write_text(INSTRUCTION)
    return d


class ShapeOverlayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sys = fake_sys(self.tmp / "sys")
        self.out = self.tmp / "out"

    def arm(self, drop=(), add_tools=()):
        return {"squad": "coding", "leader": "coder", "drop": list(drop), "add_tools": list(add_tools)}

    def test_drop_writes_members_without_dropped(self):
        shape_overlay.build_overlay(self.sys, self.arm(["code_scout", "reviewer"]), self.out)
        got = json.loads((self.out / "agents.json").read_text())
        self.assertEqual(got, {"squads": [{"name": "Coding", "members": ["code_docs"]}]})

    def test_note_names_every_dropped_member(self):
        shape_overlay.build_overlay(self.sys, self.arm(["code_scout", "reviewer"]), self.out)
        text = (self.out / "registry/agents/coder/instruction.md").read_text()
        note, rest = text.split("\n\n", 1)
        for want in ("code_scout", "reviewer", "not available"):
            self.assertIn(want, note)
        self.assertEqual(rest, INSTRUCTION)

    def test_add_tools_extends_leader_tools(self):
        shape_overlay.build_overlay(self.sys, self.arm(["reviewer"], ["serper", "ddg", "web"]), self.out)
        got = json.loads((self.out / "registry/agents/coder/agent.json").read_text())
        self.assertEqual(got["tools"], ["fs", "lsp", "web", "serper", "ddg"])
        self.assertIn("web search and fetch tools", (self.out / "registry/agents/coder/instruction.md").read_text())

    def test_reference_arm_writes_nothing(self):
        shape_overlay.build_overlay(self.sys, self.arm(), self.out)
        self.assertEqual(list(self.out.rglob("*")) if self.out.exists() else [], [])

    def test_unknown_member_is_an_error(self):
        with self.assertRaises(SystemExit):
            shape_overlay.build_overlay(self.sys, self.arm(["web_agent"]), self.out)

    def test_shipped_arms_are_the_planned_ones(self):
        arms = json.loads((Path(shape_overlay.__file__).parent / "shapes.json").read_text())
        self.assertEqual(arms["coding-C"]["drop"], ["reviewer", "code_scout"])
        self.assertEqual(arms["knowledge-C"]["add_tools"], ["serper", "ddg", "web"])
        self.assertEqual(sorted(arms), ["coding-A", "coding-B", "coding-C", "k8s-A", "k8s-B",
                                        "knowledge-A", "knowledge-B", "knowledge-C"])


if __name__ == "__main__":
    unittest.main()
