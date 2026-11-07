"""Unit tests for the pure parts of the Harbor adapter (stdlib only; no
Harbor, no docker, no model). Run: python3 -m unittest discover -s harbor"""
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_sysconf  # noqa: E402
import summarize  # noqa: E402
from omnis_harbor import usage  # noqa: E402

AGENTS = {"agents": ["coder", "code_scout", "reviewer", "curator", "reflector"], "router_squad": "omnis",
          "squads": [{"name": "Coding", "leader": "coder", "members": ["code_scout", "reviewer"]}]}

CODER_INSTRUCTION = """team instruction
- **Scout** (`code_scout`) — navigator.
- **Reviewer** (`reviewer`) — a read-only diff reviewer.
  Two rounds at most.
  - **Skip it** for setup tasks.
- **Refactorer** (`refactorer`) — refactors.
"""


def _src_tar(d: Path) -> Path:
    files = {
        "config/agents.json": json.dumps(AGENTS),
        "config/models.json": "{}", "config/permissions.json": "{}", "config/hooks.json": "{}",
        "registry/agents/coder/agent.json": json.dumps({"name": "coder", "tools": ["fs", "lsp"], "leader": True}),
        "registry/agents/coder/instruction.md": CODER_INSTRUCTION,
        "softskills/INDEX.md": "x", "README.md": "ignored",
    }
    p = d / "src.tar"
    with tarfile.open(p, "w") as tf:
        for name, body in files.items():
            data = body.encode()
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), 0o644
            tf.addfile(ti, io.BytesIO(data))
    return p


class SysconfTest(unittest.TestCase):
    def models(self):
        return make_sysconf.bench_models("m1", context_length=1000, max_output_tokens=10,
                                         in_price=1, out_price=2, cache_price=0.1)

    def test_models_never_hold_secrets_and_force_one_model(self):
        m = self.models()
        self.assertEqual(m["providers"]["bench"]["api_key"], "OPENAI_API_KEY")
        self.assertEqual(m["providers"]["bench"]["base_url"], "OPENAI_BASE_URL")
        self.assertTrue(m["override_model_enabled"])
        self.assertEqual({v["model"] for v in m["models"].values()}, {"m1"})
        self.assertIn("premium", m["models"])

    def test_full_and_lean(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            src = _src_tar(t)
            full = make_sysconf.build(src, t / "full", "full", self.models())
            self.assertFalse((full / "hooks.json").exists())
            self.assertFalse((full / "README.md").exists())
            self.assertEqual(json.loads((full / "permissions.json").read_text())["permissions"]["defaultMode"],
                             "bypassPermissions")
            a = json.loads((full / "agents.json").read_text())
            self.assertEqual(a["start_squad"], "coding")
            self.assertEqual(a["router_squad"], "none")
            self.assertNotIn("curator", a["agents"])
            self.assertEqual(a["squads"][0]["members"], ["code_scout", "reviewer"])
            self.assertEqual((full / "registry/agents/coder/instruction.md").read_text(), CODER_INSTRUCTION)

            lean = make_sysconf.build(src, t / "lean", "lean", self.models())
            a = json.loads((lean / "agents.json").read_text())
            self.assertEqual((a["squads"][0]["leader"], a["squads"][0]["members"]), ("none", ["coder"]))
            c = json.loads((lean / "registry/agents/coder/agent.json").read_text())
            self.assertEqual(c["tools"], ["fs", "tests"])
            self.assertNotIn("Scout", (lean / "registry/agents/coder/instruction.md").read_text())


class UsageTest(unittest.TestCase):
    def test_parse_and_cost(self):
        def am(agent, p, c, o, partial=False):
            resp = {"UsageMetadata": {"promptTokenCount": p, "cachedContentTokenCount": c, "candidatesTokenCount": o}}
            if partial:
                resp["Partial"] = True
            return json.dumps({"event": "after_model", "payload": {"agent": agent, "response": resp}})
        lines = [am("coder", 1000, 800, 50), am("code_scout", 500, 0, 20), am("coder", 9, 9, 9, partial=True),
                 json.dumps({"event": "before_tool", "payload": {"tool": "Bash"}}), "[12:00] summary line"]
        u = usage.parse_events(lines)
        self.assertEqual(u["total"], {"calls": 2, "prompt": 1500, "cached": 800, "output": 70})
        self.assertEqual(u["tool_calls"], 1)
        self.assertEqual(set(u["agents"]), {"coder", "code_scout"})
        # uncached 700 @1 + cached 800 @0.1 + out 70 @2 = 700+80+140 per M
        self.assertAlmostEqual(usage.cost(u["total"], 1, 2, 0.1), 920 / 1e6)
        self.assertAlmostEqual(usage.cost(u["total"], 1, 2, None), 1640 / 1e6)


class SummarizeTest(unittest.TestCase):
    def test_infra_error_is_not_a_fail(self):
        ok = {"task_name": "a", "verifier_result": {"rewards": {"reward": 1.0}},
              "agent_result": {"cost_usd": 0.2, "n_input_tokens": 10, "n_output_tokens": 1, "metadata": {"variant": "lean"}}}
        bad = {"task_name": "b", "exception_info": {"exception_type": "RuntimeError"}}
        miss = {"task_name": "c", "verifier_result": {"rewards": {"reward": 0.0}}, "agent_result": {"cost_usd": 0.2}}
        rows = [summarize.trial_row(r) for r in (ok, bad, miss)]
        t = summarize.totals(rows)
        self.assertEqual((t["scored"], t["resolved"], t["infra_errors"]), (2, 1, 1))
        self.assertAlmostEqual(t["cost_per_resolved"], 0.4)


if __name__ == "__main__":
    unittest.main()


class NoReviewVariantTest(unittest.TestCase):
    def test_full_noreview_drops_only_the_reviewer(self):
        models = make_sysconf.bench_models("m1", context_length=1000, max_output_tokens=10,
                                           in_price=1, out_price=2, cache_price=0.1)
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            out = make_sysconf.build(_src_tar(t), t / "nr", "full-noreview", models)
            a = json.loads((out / "agents.json").read_text())
            coding = [q for q in a["squads"] if q["name"] == "Coding"][0]
            self.assertEqual(coding["members"], ["code_scout"])
            self.assertEqual(coding["leader"], "coder")
            instr = (out / "registry/agents/coder/instruction.md").read_text()
            self.assertNotIn("reviewer", instr.lower())
            self.assertIn("Scout", instr)
            self.assertIn("Refactorer", instr)

    def test_strip_reviewer_refuses_a_missing_bullet(self):
        with self.assertRaises(SystemExit):
            make_sysconf.strip_reviewer("no team here\n")

