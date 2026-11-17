import json
import os
import unittest

import memory_bench

HERE = os.path.dirname(os.path.abspath(__file__))


def scenario(sid):
    with open(os.path.join(HERE, "tasks-memory.json")) as f:
        return next(s for s in json.load(f)["scenarios"] if s["id"] == sid)


def mem(body, name="x", description="d"):
    return {"name": name, "description": description, "type": "feedback", "body": body}


class EvaluateTest(unittest.TestCase):
    def test_correction_pass_and_leak(self):
        s = scenario("correction")
        ok = memory_bench.evaluate(s, ["a", "b", "[search-svc] Fix crash", "Fix crash"],
                                   [mem("Prefix commits with [search-svc], in English.")])
        self.assertTrue(all(ok.values()), ok)
        leak = memory_bench.evaluate(s, ["a", "b", "[search-svc] Fix", "[search-svc] Fix"], [mem("search-svc")])
        self.assertFalse(leak["step4_answer_not"])

    def test_update_stale_value_and_duplicates(self):
        s = scenario("update")
        good = memory_bench.evaluate(s, ["", "", "9443"], [mem("Billing listens on 9443 (was 8443).", "billing-port")])
        self.assertTrue(all(good.values()), good)
        stale = memory_bench.evaluate(s, ["", "", "8443"],
                                      [mem("Facturation: port 8443", "a"), mem("Facturation: port 9443", "b")])
        self.assertFalse(stale["step3_answer"])
        self.assertFalse(stale["step3_answer_not"])
        self.assertFalse(stale["stale_value_gone"])
        self.assertFalse(stale["no_duplicate"])

    def test_forget_and_no_pollution(self):
        f = memory_bench.evaluate(scenario("forget"), ["", "", "Je ne sais pas."], [])
        self.assertTrue(all(f.values()), f)
        self.assertFalse(memory_bench.evaluate(scenario("forget"), ["", "", "Linear"], [mem("Linear")])["memory_absent"])
        p = memory_bench.evaluate(scenario("no-pollution"), ["391"], [mem("x")])
        self.assertFalse(p["memory_count"])
        self.assertTrue(p["step1_answer"])


if __name__ == "__main__":
    unittest.main()


def test_confirmation_checks():
    import memory_bench as mb
    scn = {"steps": [], "min_confirmations": {"re": "vendredi", "min": 1}, "max_confirmations": 0}
    ok = mb.evaluate(scn, [], [{"name": "no-friday", "body": "pas le vendredi", "confirmations": 1}])
    assert ok["confirmed"] and not ok["no_false_confirm"]
    no = mb.evaluate({"steps": [], "min_confirmations": {"re": "vendredi", "min": 1}}, [], [{"name": "x", "body": "pas le vendredi"}])
    assert not no["confirmed"]
