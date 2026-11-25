#!/usr/bin/env python3
"""Tests for replay. Run: python3 -m unittest discover -s session-study"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import judge
import replay

FAIL = {"id": "ss-1", "squad": "knowledge", "prompt": "Q",
        "rubric": {"pass": ["a"], "failure": "repeats the same search"}}
CTRL = {"id": "ss-c1", "squad": "knowledge", "prompt": "Q", "rubric": {"pass": ["a"], "failure": ""}}


def run_row(valid=True, passed=True, seen=False):
    return {"valid": valid, "passed": passed, "failure_seen": seen}


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


class MaterialiseTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def test_materialise_writes_files_and_strips_rubric(self):
        path = replay.materialise([dict(FAIL, kind="web", files={"a.txt": "hi", "sub/b.md": "yo"}),
                                   {"id": "ss-2", "squad": "system", "prompts": ["one", "two"],
                                    "rubric": {"pass": ["a"], "failure": "f"}}], self.out)
        with open(path) as f:
            tasks = json.load(f)
        task = tasks[0]
        self.assertNotIn("rubric", task)
        self.assertNotIn("files", task)
        self.assertEqual((task["id"], task["squad"], task["prompt"], task["kind"]), ("ss-1", "knowledge", "Q", "web"))
        with open(os.path.join(task["cwd"], "a.txt")) as f:
            self.assertEqual(f.read(), "hi")
        self.assertTrue(os.path.exists(os.path.join(task["cwd"], "sub", "b.md")))
        self.assertEqual(tasks[1]["prompts"], ["one", "two"])
        self.assertNotIn("cwd", tasks[1])

    def test_materialise_refuses_a_file_name_that_leaves_the_fixture_dir(self):
        for name in ("../x", "/etc/x", "a/../../x", "a\\b", ""):
            with self.assertRaises(ValueError, msg=name):
                replay.materialise([dict(FAIL, files={name: "x"})], self.out)


class OutcomeTest(unittest.TestCase):
    def test_valid_rejects_timeout_ask_user_and_empty_answer(self):
        self.assertTrue(replay.valid({"status": "done", "answer": "text"}))
        for rec in ({"status": "timeout", "answer": "t"}, {"status": "cancelled", "answer": "t"},
                    {"status": "ask_user", "answer": "t"}, {"status": "error", "answer": "t"},
                    {"status": "done", "answer": "  "}, {}):
            self.assertFalse(replay.valid(rec), rec)

    def test_outcome_reproduces_at_two_of_five(self):
        two = [run_row(seen=True, passed=False)] * 2 + [run_row()] * 3
        self.assertEqual(replay.outcome(FAIL, two),
                         {"runs": 5, "invalid": 0, "passed": 3, "failure_seen": 2, "status": "reproduces"})
        one = [run_row(seen=True, passed=False)] + [run_row()] * 4
        self.assertEqual(replay.outcome(FAIL, one)["status"], "does_not_reproduce")

    def test_outcome_not_measured_with_three_invalid_runs(self):
        runs = [run_row(valid=False)] * 3 + [run_row(seen=True)] * 2
        self.assertEqual(replay.outcome(FAIL, runs)["status"], "not_measured")
        self.assertEqual(replay.outcome(FAIL, [])["status"], "not_measured")
        self.assertEqual(replay.outcome(FAIL, [run_row()] * 2)["status"], "not_measured")

    def test_invalid_run_never_counts_as_failure_seen(self):
        runs = [{"valid": False, "passed": False, "failure_seen": True}] * 2 + [run_row()] * 3
        o = replay.outcome(FAIL, runs)
        self.assertEqual((o["failure_seen"], o["status"]), (0, "does_not_reproduce"))

    def test_control_ok_at_four_of_five(self):
        self.assertEqual(replay.outcome(CTRL, [run_row()] * 4 + [run_row(passed=False)])["status"], "control_ok")
        self.assertEqual(replay.outcome(CTRL, [run_row()] * 3 + [run_row(passed=False)] * 2)["status"], "control_fails")
        self.assertEqual(replay.outcome(CTRL, [run_row()] * 2)["status"], "not_measured")


class RunReplayTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.started = []

    def run_ok(self, cost=0.4, status="done"):
        def run(task_id):
            self.started.append(task_id)
            return {"task": task_id, "status": status, "answer": "an answer", "total_cost_usd": cost}
        return run

    @staticmethod
    def judge_ok(scenario, record):
        return {"passed": True, "failure_seen": False, "reason": "fine"}

    def test_replay_runs_and_judges_every_scenario(self):
        s = replay.run_replay([FAIL, CTRL], self.out, 2, 30.0, self.run_ok(), self.judge_ok)
        self.assertEqual(s, {"runs": 4, "stopped": "done"})
        self.assertEqual(self.started, ["ss-1", "ss-1", "ss-c1", "ss-c1"])
        judged = rows(os.path.join(self.out, "run-judged.jsonl"))
        self.assertEqual([(r["scenario"], r["run"], r["valid"]) for r in judged],
                         [("ss-1", 0, True), ("ss-1", 1, True), ("ss-c1", 0, True), ("ss-c1", 1, True)])
        self.assertAlmostEqual(replay.spent(os.path.join(self.out, "ledger.jsonl")), 1.6)

    def test_replay_stops_at_ceiling(self):
        s = replay.run_replay([FAIL], self.out, 5, 1.0, self.run_ok(0.4), self.judge_ok)
        self.assertEqual(s, {"runs": 3, "stopped": "ceiling"})

    def test_replay_resumes(self):
        replay.run_replay([FAIL], self.out, 3, 30.0, self.run_ok(), self.judge_ok)
        self.started.clear()
        s = replay.run_replay([FAIL], self.out, 5, 30.0, self.run_ok(), self.judge_ok)
        self.assertEqual((s["runs"], self.started), (2, ["ss-1", "ss-1"]))
        self.assertEqual(len(rows(os.path.join(self.out, "run-judged.jsonl"))), 5)

    def test_invalid_run_is_recorded_and_not_judged(self):
        asked = []
        replay.run_replay([FAIL], self.out, 1, 30.0, self.run_ok(status="timeout"),
                          lambda s, r: asked.append(1) or self.judge_ok(s, r))
        self.assertEqual(asked, [])
        self.assertEqual(rows(os.path.join(self.out, "run-judged.jsonl")),
                         [{"scenario": "ss-1", "run": 0, "valid": False, "passed": False, "failure_seen": False,
                           "reason": "invalid run: timeout"}])

    def test_a_judge_error_is_retried_on_the_next_run(self):
        def boom(scenario, record):
            raise ValueError("not json")
        replay.run_replay([FAIL], self.out, 1, 30.0, self.run_ok(), boom)
        self.assertIn("error", rows(os.path.join(self.out, "run-judged.jsonl"))[0])
        self.started.clear()
        replay.run_replay([FAIL], self.out, 1, 30.0, self.run_ok(), self.judge_ok)
        judged = rows(os.path.join(self.out, "run-judged.jsonl"))
        self.assertEqual((self.started, len(judged), judged[0]["passed"]), ([], 1, True))

    def test_a_run_that_cannot_start_stops_the_replay(self):
        def broken(task_id):
            raise RuntimeError("bench.py exited 2")
        with self.assertRaises(RuntimeError):
            replay.run_replay([FAIL], self.out, 1, 30.0, broken, self.judge_ok)


class RunJudgeTest(unittest.TestCase):
    def test_run_prompt_shows_rubric_answer_and_metrics(self):
        rec = {"answer": "THE-ANSWER", "total_cost_usd": 0.5, "wall_ms": 61000, "fetches": 12,
               "delegations": {"web_agent": 3}, "leader_tools": {"WebSearch": 4}, "subagent_tools": {}}
        system, user = judge.run_prompt(FAIL, rec)
        for part in ("THE-ANSWER", "repeats the same search", "web_agent", "12", "0.5"):
            self.assertIn(part, user)
        self.assertIn("specific", system)

    def test_parse_run(self):
        self.assertEqual(judge.parse_run('{"passed": true, "failure_seen": false, "reason": "ok"}'),
                         {"passed": True, "failure_seen": False, "reason": "ok"})
        for bad in ('{"passed": "yes", "failure_seen": false}', '{"passed": true}', "nope"):
            with self.assertRaises(ValueError, msg=bad):
                judge.parse_run(bad)


if __name__ == "__main__":
    unittest.main()
