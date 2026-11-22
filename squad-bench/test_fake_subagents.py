#!/usr/bin/env python3
"""Tests for fake_subagents. Run: python3 -m unittest squad-bench/test_fake_subagents.py"""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

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


def chat(agent, text, stream=False):
    return {"model": "fake-" + agent, "stream": stream,
            "messages": [{"role": "user", "content": text}]}


class TestServer(unittest.TestCase):
    def setUp(self):
        self.srv = fs.serve(0)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, args=(0.01,), daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def raw(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()

    def post(self, path, body):
        return json.loads(self.raw(path, body))

    def get(self, path):
        return json.loads(self.raw(path))

    def scenario(self, rules):
        return self.post("/scenario", {"task": "t", "script": {"investigator": rules}})

    def test_chat_reply_and_log(self):
        self.assertEqual(self.scenario([{"reply": "found", "delay_ms": 0}]), {"ok": True})
        r = self.post("/v1/chat/completions", chat("investigator", "why"))
        self.assertEqual(r["choices"][0]["message"]["content"], "found")
        self.assertEqual(r["choices"][0]["finish_reason"], "stop")
        out = self.get("/calls")
        self.assertEqual(out["task"], "t")
        self.assertEqual([(c["agent"], c["n"], c["request"], c["rule"]) for c in out["calls"]],
                         [("investigator", 1, "why", 0)])
        self.assertLessEqual(out["calls"][0]["started_ms"], out["calls"][0]["ended_ms"])

    def test_streaming_reply(self):
        self.scenario([{"reply": "found", "delay_ms": 0}])
        body = self.raw("/v1/chat/completions", chat("investigator", "why", stream=True))
        self.assertIn('"content": "found"', body)
        self.assertTrue(body.rstrip().endswith("data: [DONE]"))

    def test_bad_scenario_is_refused_and_keeps_the_previous_one(self):
        self.scenario([{"reply": "found", "delay_ms": 0}])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/scenario", {"task": "t2", "script": {"investigator": [{"delay_ms": 1}]}})
        self.assertEqual(cm.exception.code, 400)
        self.assertIn("error", json.loads(cm.exception.read()))
        cm.exception.close()
        r = self.post("/v1/chat/completions", chat("investigator", "why"))
        self.assertEqual(r["choices"][0]["message"]["content"], "found")
        self.assertEqual(self.get("/calls")["task"], "t")

    def test_scenario_clears_the_log(self):
        self.scenario([{"reply": "found", "delay_ms": 0}])
        self.post("/v1/chat/completions", chat("investigator", "why"))
        self.scenario([{"reply": "found", "delay_ms": 0}])
        self.assertEqual(self.get("/calls")["calls"], [])

    def test_no_scenario_answers_the_default(self):
        r = self.post("/v1/chat/completions", chat("helper", "x"))
        self.assertEqual(r["choices"][0]["message"]["content"], "No evidence found.")

    def test_status_rule_returns_that_status(self):
        self.scenario([{"status": 503, "delay_ms": 0}])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/v1/chat/completions", chat("investigator", "why"))
        self.assertEqual(cm.exception.code, 503)
        cm.exception.close()
        self.assertEqual(len(self.get("/calls")["calls"]), 1)

    def test_models_endpoint(self):
        self.assertEqual(self.get("/v1/models"), {"data": []})

    def parallel(self, n, text="why"):
        replies = []
        def one(i):
            r = self.post("/v1/chat/completions", chat("investigator", f"{text} {i}"))
            replies.append(r["choices"][0]["message"]["content"])
        threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return replies

    def test_parallel_calls_are_all_logged_and_times_is_respected(self):
        self.scenario([{"times": 2, "reply": "limited", "delay_ms": 50}])
        replies = self.parallel(8)
        calls = self.get("/calls")["calls"]
        self.assertEqual(sorted(c["n"] for c in calls), list(range(1, 9)))
        self.assertEqual(replies.count("limited"), 2)
        self.assertEqual(replies.count("No evidence found."), 6)

    def test_overlapping_calls_overlap_in_the_log(self):
        self.scenario([{"reply": "r", "delay_ms": 200}])
        self.parallel(2)
        a, b = sorted(self.get("/calls")["calls"], key=lambda c: c["started_ms"])
        self.assertGreater(a["ended_ms"], b["started_ms"])


if __name__ == "__main__":
    unittest.main()
