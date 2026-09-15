#!/usr/bin/env python3
"""Unit tests for k8s-ai-bench/omnis-agent's pure logic.

`omnis-agent` is a standalone script with no `.py` suffix (it must present as
a `kubectl-ai`-shaped CLI binary), so it can't be `import`ed the normal way.
It IS cleanly importable via `importlib.machinery.SourceFileLoader` -- the
module has a plain `if __name__ == "__main__": sys.exit(main())` guard, so
loading it only defines functions/constants and runs no I/O. This test module
exists specifically so pure-logic regressions (like the cache-billing double
charge below) have real, run-in-CI coverage instead of manual verification.

Run: python3 -m unittest discover -s k8s-ai-bench -v
(or directly: python3 k8s-ai-bench/test_omnis_agent.py)
"""
import importlib.util
import time
import json
import io
import os
import unittest
from unittest import mock
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT_PATH = os.path.join(HERE, "omnis-agent")


def _load_omnis_agent():
    loader = SourceFileLoader("omnis_agent_under_test", AGENT_PATH)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


agent = _load_omnis_agent()


class TestNoteUsageCacheBilling(unittest.TestCase):
    """note_usage's cost estimate mirrors squad-bench's note_model (see
    squad-bench/bench.py and commit 6cb1466). `prompt_tokens` follows the
    OpenAI usage convention and already INCLUDES `cache_read_tokens` as a
    subset, not an addition. Billing the full `prompt_tokens` at the input
    price AND `cache_read_tokens` at the cache-read price double-charges the
    cached portion. Correct: the uncached remainder (prompt - cache_read,
    clamped at zero) pays the input price; cache_read pays the (usually much
    cheaper) cache-read price; output pays the output price."""

    def test_cache_hit_is_not_double_charged(self):
        """Same reference record squad-bench's regression test uses: 182311
        prompt / 153089 cache-read (84% hit) / 3052 output at ChapsVision
        Premium prices ($3.15/$15.75/$0.30 per M). The broken formula (prompt
        tokens AND cache_read_tokens both billed in full) reads ~$0.668275;
        the correct figure is ~$0.186045."""
        usage = {}
        agent.note_usage(usage, {
            "agent": "web_agent",
            "prompt_tokens": 182311,
            "output_tokens": 3052,
            "cache_read_tokens": 153089,
            "in_price_per_m": 3.15,
            "out_price_per_m": 15.75,
            "cache_read_price_per_m": 0.30,
        })
        cost = usage["web_agent"]["est_cost_usd"]
        self.assertAlmostEqual(cost, 0.186045, places=5)
        self.assertLess(cost, 0.4, "must not land anywhere near the broken $0.668275 figure")

    def test_no_cache_path_is_unchanged(self):
        """cache_read_tokens == 0 must produce exactly prompt*in + out*out --
        the backward-compatibility guarantee for non-caching records."""
        usage = {}
        agent.note_usage(usage, {
            "agent": "leader",
            "prompt_tokens": 50000,
            "output_tokens": 1200,
            "cache_read_tokens": 0,
            "in_price_per_m": 5.0,
            "out_price_per_m": 25.0,
            "cache_read_price_per_m": 0.5,
        })
        e = usage["leader"]
        expected = round(50000 * 5.0 / 1e6 + 1200 * 25.0 / 1e6, 6)
        self.assertEqual(e["est_cost_usd"], expected)

    def test_accumulates_across_calls(self):
        """note_usage is called once per turn_usage frame and must SUM across
        calls, not overwrite -- both the raw counters and the cost estimate."""
        usage = {}
        prices = {"in_price_per_m": 2.0, "out_price_per_m": 10.0, "cache_read_price_per_m": 0.5}
        agent.note_usage(usage, dict(agent="a", prompt_tokens=1000, output_tokens=100,
                                      cache_read_tokens=400, **prices))
        agent.note_usage(usage, dict(agent="a", prompt_tokens=2000, output_tokens=200,
                                      cache_read_tokens=1500, **prices))
        e = usage["a"]
        self.assertEqual(e["prompt_tok"], 3000)
        self.assertEqual(e["cache_read_tok"], 1900)
        self.assertEqual(e["out_tok"], 300)
        self.assertEqual(e["calls"], 2)
        cost1 = (600 * 2.0 + 400 * 0.5 + 100 * 10.0) / 1e6
        cost2 = (500 * 2.0 + 1500 * 0.5 + 200 * 10.0) / 1e6
        self.assertAlmostEqual(e["est_cost_usd"], cost1 + cost2, places=6)

    def test_cache_read_over_prompt_tokens_is_clamped_not_negative(self):
        """Defensive: if a provider ever reports cache_read_tokens >
        prompt_tokens, (prompt - cache_read) must clamp at zero rather than
        produce a silently negative charge."""
        usage = {}
        agent.note_usage(usage, {
            "agent": "odd",
            "prompt_tokens": 100,
            "output_tokens": 10,
            "cache_read_tokens": 150,
            "in_price_per_m": 10.0,
            "out_price_per_m": 20.0,
            "cache_read_price_per_m": 1.0,
        })
        cost = usage["odd"]["est_cost_usd"]
        self.assertGreaterEqual(cost, 0.0)
        self.assertAlmostEqual(cost, (150 * 1.0 + 10 * 20.0) / 1e6, places=6)


if __name__ == "__main__":
    unittest.main()


def _sse(*frames):
    """Build an SSE byte-line stream: each frame is (seq, event, data-dict)."""
    out = []
    for seq, ev, data in frames:
        if seq is not None:
            out.append(f"id: {seq}".encode())
        out.append(f"event: {ev}".encode())
        out.append(("data: " + json.dumps(data)).encode())
        out.append(b"")
    return out


class TestAskUserAborts(unittest.TestCase):
    """omnis-agent can never answer an `ask_user` prompt: the harness runs it
    non-interactively with stdin already consumed. Streaming on until the
    deadline turns an unanswerable question into a 10-minute task timeout that
    reads like a model failure. Abort the moment the frame arrives."""

    def test_ask_user_frame_raises_abort(self):
        mod = _load_omnis_agent()
        stream = _sse(
            (1, "token", {"text": "hi"}),
            (2, "ask_user", {"prompt": "delete pod foo?"}),
        )
        with self.assertRaises(mod.AskUserAbort):
            mod.consume(stream, io.StringIO(), [], {}, time.time(), 300)

    def test_the_abort_carries_the_prompt_so_the_operator_sees_what_was_asked(self):
        mod = _load_omnis_agent()
        stream = _sse((1, "ask_user", {"prompt": "delete pod foo?"}))
        with self.assertRaises(mod.AskUserAbort) as ctx:
            mod.consume(stream, io.StringIO(), [], {}, time.time(), 300)
        self.assertIn("delete pod foo?", str(ctx.exception))

    def test_main_reports_the_prompt_and_exits_on_its_own_code(self):
        """A traceback is not an acceptable way to say 'someone asked a question'
        (the script applies that rule to unreadable hook input already), and the
        exit code must be distinguishable from 'the run simply did not finish'."""
        mod = _load_omnis_agent()
        stream = _sse((1, "ask_user", {"prompt": "delete pod foo?"}))
        err = io.StringIO()
        env = {"OMNIS_SERVER": "http://x", "OMNIS_BENCH_DEADLINE": "5"}
        with mock.patch.object(mod, "api", lambda *a, **k: {"session_id": "s1"}), \
             mock.patch.object(mod, "_req", lambda *a, **k: stream), \
             mock.patch.object(mod, "kubeconfig_context", lambda _p: "ctx"), \
             mock.patch.object(mod.sys, "stdin", io.StringIO("fix the deployment")), \
             mock.patch.object(mod.sys, "stderr", err), \
             mock.patch.object(mod.sys, "argv", ["omnis-agent"]), \
             mock.patch.dict(mod.os.environ, env, clear=False):
            mod.os.environ.pop("OMNIS_SHARED_CONTEXT", None)
            rc = mod.main()
        self.assertEqual(rc, 3, "ask_user needs its own exit code, not 1")
        self.assertIn("delete pod foo?", err.getvalue())


class TestSessionCleanup(unittest.TestCase):
    """run.sh drives 24 tasks through ONE shared server. Each omnis-agent call
    opens a session and never closed it, so they piled up for the whole run."""

    def _run_main(self, stream):
        mod = _load_omnis_agent()
        calls = []

        def fake_api(method, base, path, token, body=None):
            calls.append((method, path))
            return {"session_id": "s1"}

        env = {"OMNIS_SERVER": "http://x", "OMNIS_BENCH_DEADLINE": "5"}
        with mock.patch.object(mod, "api", fake_api), \
             mock.patch.object(mod, "_req", lambda *a, **k: stream), \
             mock.patch.object(mod, "kubeconfig_context", lambda _p: "ctx"), \
             mock.patch.object(mod.sys, "stdin", io.StringIO("do a thing")), \
             mock.patch.object(mod.sys, "stderr", io.StringIO()), \
             mock.patch.object(mod.sys, "argv", ["omnis-agent"]), \
             mock.patch.dict(mod.os.environ, env, clear=False):
            mod.os.environ.pop("OMNIS_SHARED_CONTEXT", None)
            rc = mod.main()
        return rc, calls

    def test_the_session_is_deleted_when_the_task_finishes(self):
        rc, calls = self._run_main(_sse((1, "done", {})))
        self.assertEqual(rc, 0)
        self.assertTrue(any(m == "DELETE" and p.endswith("/s1") for m, p in calls),
                        f"session left open on the shared server; calls={calls}")

    def test_the_session_is_deleted_even_when_a_prompt_aborts_the_run(self):
        rc, calls = self._run_main(_sse((1, "ask_user", {"prompt": "confirm?"})))
        self.assertEqual(rc, 3)
        self.assertTrue(any(m == "DELETE" and p.endswith("/s1") for m, p in calls),
                        f"session left open after an abort; calls={calls}")
