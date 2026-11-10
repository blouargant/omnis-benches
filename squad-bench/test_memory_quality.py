import json
import os
import unittest

import memory_quality as mq

HERE = os.path.dirname(os.path.abspath(__file__))


def conv(cid):
    with open(os.path.join(HERE, "tasks-memory-quality.json")) as f:
        return next(c for c in json.load(f)["conversations"] if c["id"] == cid)


def record(c):
    return {
        "turns": [{"prompt": p, "answer": "ok", "status": "done",
                   "memory_tools": {"memory_save": 1 if i == 1 else 0, "memory_delete": 0, "memory_read": 0}}
                  for i, p in enumerate(c["turns"])],
        "memories": [{"name": "no-regexp", "type": "feedback", "description": "Validation by hand", "body": "Never regexp."}],
        "recall": [{"id": q["id"], "answer": "réponse " + q["id"]} for q in c["recall"]],
    }


class JudgePromptTest(unittest.TestCase):
    def test_prompt_carries_everything_the_judge_needs(self):
        c = conv("orders-api")
        p = mq.build_judge_prompt(c, record(c))
        for needle in ("### Turn 2", '"memory_save": 1', "E5 (feedback)", "F3:", "### no-regexp [feedback]",
                       "EXPECT:", "réponse R3", '"overall"'):
            self.assertIn(needle, p)
        self.assertNotIn('"memory_save": 0', p)  # turns without memory calls carry no tool line

    def test_optional_items_listed(self):
        c = conv("newsletter")
        self.assertIn("O1:", mq.build_judge_prompt(c, record(c)))

    def test_no_memories(self):
        c = conv("newsletter")
        r = record(c)
        r["memories"] = []
        self.assertIn("(none)", mq.build_judge_prompt(c, r))


class ParseTest(unittest.TestCase):
    def test_fenced_and_prose(self):
        self.assertEqual(mq.parse_judge('```json\n{"overall": 7}\n```'), {"overall": 7})
        self.assertEqual(mq.parse_judge('Voici : {"a": {"b": 1}} fin'), {"a": {"b": 1}})
        with self.assertRaises(ValueError):
            mq.parse_judge("nothing here")


class ScoreTest(unittest.TestCase):
    def test_scores(self):
        c = conv("newsletter")  # 4 expected, 2 recall questions
        v = {"expected": [{"id": "E1", "status": "present"}, {"id": "E2", "status": "partial"},
                          {"id": "E3", "status": "missing"}, {"id": "E4", "status": "present"}],
             "forbidden": [{"id": "F1", "violated": True}, {"id": "F2", "violated": False}],
             "memories": [{"justified": True, "faithful": 2}, {"justified": False, "faithful": 1, "duplicate_of": "x"}],
             "recall": [{"id": "R1", "score": 2}, {"id": "R2", "score": 1}], "overall": 6}
        s = mq.score(c, v)
        self.assertEqual(s["recall"], 0.625)
        self.assertEqual(s["precision"], 0.5)
        self.assertEqual(s["violations"], 1)
        self.assertEqual(s["duplicates"], 1)
        self.assertEqual(s["faithful"], 0.75)
        self.assertEqual(s["application"], 0.75)
        self.assertEqual(s["overall"], 6)

    def test_empty_memory(self):
        s = mq.score(conv("newsletter"), {"expected": [], "memories": [], "recall": []})
        self.assertEqual(s["recall"], 0.0)
        self.assertIsNone(s["precision"])
        self.assertIsNone(s["faithful"])


if __name__ == "__main__":
    unittest.main()
