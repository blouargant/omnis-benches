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



SHIPPED_MODELS = {
    "providers": {"openai-compat": {"kind": "openai_compat", "base_url": "https://gw.example/v1", "api_key": "sk-x"}},
    "models": {
        "premium": {"provider_ref": "openai-compat", "model": "claude-sonnet-5-5",
                    "input_token_price_per_million": 2.1, "output_token_price_per_million": 10.5,
                    "cached_input_token_price_per_million": 0.21},
        "simple": {"provider_ref": "openai-compat", "model": "Simple",
                   "input_token_price_per_million": 0.2625, "output_token_price_per_million": 0.525},
    },
    "embed_model_ref": "embedder", "override_model_ref": "x", "override_model_enabled": True,
}


def _tiered_tar(d: Path) -> Path:
    files = {
        "config/agents.json": json.dumps({"agents": ["coder", "code_scout", "reviewer", "code_docs"], "squads": [
            {"name": "Coding", "leader": "coder", "members": ["code_scout", "reviewer", "code_docs"]}]}),
        "config/models.json": json.dumps(SHIPPED_MODELS),
        "config/permissions.json": "{}",
        "registry/agents/coder/agent.json": json.dumps({"name": "coder", "tools": ["fs"], "leader": True, "model_ref": "premium"}),
        "registry/agents/coder/instruction.md": CODER_INSTRUCTION,
        "registry/agents/code_scout/agent.json": json.dumps({"name": "code_scout", "model_ref": "simple"}),
        "registry/agents/reviewer/agent.json": json.dumps({"name": "reviewer", "model_ref": "simple"}),
        "registry/agents/code_docs/agent.json": json.dumps({"name": "code_docs"}),
    }
    p = d / "src.tar"
    with tarfile.open(p, "w") as tf:
        for name, body in files.items():
            data = body.encode()
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), 0o644
            tf.addfile(ti, io.BytesIO(data))
    return p


class TieredTest(unittest.TestCase):
    def test_tiered_models_keep_tiers_and_disable_override(self):
        m = make_sysconf.tiered_models(SHIPPED_MODELS)
        self.assertEqual(set(m["models"]), {"premium", "simple"})
        self.assertEqual(m["models"]["premium"]["input_token_price_per_million"], 2.1)
        self.assertFalse(m["override_model_enabled"])
        self.assertEqual(m["embed_model_ref"], "")
        self.assertEqual(m["providers"]["openai-compat"]["base_url"], "OPENAI_BASE_URL")
        self.assertEqual(m["providers"]["openai-compat"]["api_key"], "OPENAI_API_KEY")

    def test_agent_prices_follow_model_ref(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            out = make_sysconf.build(_tiered_tar(t), t / "s", "full", None)
            p = usage.agent_prices(out)
            self.assertEqual(p["coder"], (2.1, 10.5, 0.21))
            self.assertEqual(p["code_scout"], (0.2625, 0.525, None))
            self.assertEqual(p["code_docs"], (2.1, 10.5, 0.21))  # no model_ref: the leader's

    def test_cost_by_agent_sums_each_agent_at_its_price(self):
        agents = {"coder": {"calls": 1, "prompt": 1_000_000, "cached": 900_000, "output": 100_000},
                  "code_scout": {"calls": 1, "prompt": 1_000_000, "cached": 0, "output": 0}}
        prices = {"coder": (2.1, 10.5, 0.21), "code_scout": (0.2625, 0.525, None)}
        self.assertAlmostEqual(usage.cost_by_agent(agents, prices, (9, 9, 9)), 1.7115)
        self.assertAlmostEqual(usage.cost_by_agent({"?": {"calls": 1, "prompt": 1_000_000, "cached": 0, "output": 0}},
                                                   prices, (1, 1, None)), 1.0)

    def test_shape_overlay_lands_in_user_layer(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            out = make_sysconf.build(_tiered_tar(t), t / "s", "full", None, shape="coding-C")
            a = json.loads((out / "overlay/agents.json").read_text())
            self.assertEqual(a["squads"][0]["members"], ["code_docs"])
            self.assertIn("not available", (out / "overlay/registry/agents/coder/instruction.md").read_text())
            # the shipped layer itself is untouched
            self.assertEqual(json.loads((out / "agents.json").read_text())["squads"][0]["members"],
                             ["code_scout", "reviewer", "code_docs"])
            cmd = make_sysconf.overlay_seed_cmd("/r/sysconf", "/h")
            self.assertEqual(cmd, "if [ -d /r/sysconf/overlay ]; then cp -r /r/sysconf/overlay/. /h/; fi")
