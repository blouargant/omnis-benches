#!/usr/bin/env python3
"""Tests for fake_overlay. Run: python3 -m unittest squad-bench/test_fake_overlay.py"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_overlay


def fake_sys(d: Path) -> Path:
    for name in ("leader", "investigator", "summariser"):
        (d / "registry/agents" / name).mkdir(parents=True)
        (d / "registry/agents" / name / "agent.json").write_text(json.dumps({"name": name}))
    return d


def load(p: Path):
    return json.loads(p.read_text())


class TestFakeOverlay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sys = fake_sys(Path(self.tmp.name) / "sys")
        self.out = Path(self.tmp.name) / "out"

    def test_models_and_agents_point_at_the_fake_server(self):
        out = fake_overlay.build_overlay(self.sys, ["investigator", "summariser"], 18770, self.out,
                                         leader="leader", leader_model="balanced")
        self.assertEqual(out, self.out)
        self.assertEqual(load(out / "models.json"), {
            "providers": {"fake": {"kind": "openai_compat",
                                   "base_url": "http://127.0.0.1:18770/v1", "api_key": "x"}},
            "models": {name: {"provider_ref": "fake", "model": name, "context_length": 200000,
                              "input_token_price_per_million": 0, "output_token_price_per_million": 0}
                       for name in ("fake-investigator", "fake-summariser")},
            "override_model_enabled": False})
        self.assertEqual(load(out / "registry/agents/investigator/agent.json"),
                         {"model_ref": "fake-investigator"})
        self.assertEqual(load(out / "registry/agents/summariser/agent.json"),
                         {"model_ref": "fake-summariser"})
        self.assertEqual(load(out / "registry/agents/leader/agent.json"), {"model_ref": "balanced"})

    def test_several_leaders_get_the_model(self):
        (self.sys / "registry/agents/coder").mkdir()
        out = fake_overlay.build_overlay(self.sys, ["investigator"], 18770, self.out,
                                         leader=["leader", "coder"], leader_model="balanced")
        for name in ("leader", "coder"):
            self.assertEqual(load(out / "registry/agents" / name / "agent.json"), {"model_ref": "balanced"})
        with self.assertRaises(SystemExit):
            fake_overlay.build_overlay(self.sys, ["investigator"], 18770, self.out,
                                       leader=["leader", "investigator"], leader_model="balanced")

    def test_leader_is_left_alone_by_default(self):
        out = fake_overlay.build_overlay(self.sys, ["investigator"], 18770, self.out)
        self.assertFalse((out / "registry/agents/leader").exists())

    def test_unknown_agent_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            fake_overlay.build_overlay(self.sys, ["nope"], 18770, self.out)
        self.assertIn("nope", str(cm.exception))

    def test_unknown_leader_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            fake_overlay.build_overlay(self.sys, ["investigator"], 18770, self.out,
                                       leader="boss", leader_model="balanced")
        self.assertIn("boss", str(cm.exception))

    def test_faking_the_leader_is_refused(self):
        with self.assertRaises(SystemExit):
            fake_overlay.build_overlay(self.sys, ["leader"], 18770, self.out,
                                       leader="leader", leader_model="balanced")

    def test_leader_without_a_model_is_refused(self):
        with self.assertRaises(SystemExit):
            fake_overlay.build_overlay(self.sys, ["investigator"], 18770, self.out, leader="leader")
        with self.assertRaises(SystemExit):
            fake_overlay.build_overlay(self.sys, ["investigator"], 18770, self.out,
                                       leader_model="balanced")

    def test_nothing_to_fake_is_refused(self):
        with self.assertRaises(SystemExit):
            fake_overlay.build_overlay(self.sys, [], 18770, self.out)


if __name__ == "__main__":
    unittest.main()
