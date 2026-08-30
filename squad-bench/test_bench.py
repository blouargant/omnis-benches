#!/usr/bin/env python3
"""Unit tests for squad-bench pure logic. Run: python3 -m unittest discover -s squad-bench"""
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scoring


class TestMatchRule(unittest.TestCase):
    def test_regex_form_is_case_insensitive(self):
        self.assertTrue(scoring.match_rule("/actuateur|actionneur/", "un ACTUATEUR"))

    def test_substring_form_is_case_insensitive(self):
        self.assertTrue(scoring.match_rule("9820772380", "ref 9820772380 ok"))
        self.assertFalse(scoring.match_rule("9820772380", "ref 123"))

    def test_empty_pattern_never_matches(self):
        self.assertFalse(scoring.match_rule("", "anything"))


class TestScoreFacts(unittest.TestCase):
    def test_on_index_selects_the_right_turn(self):
        facts = [{"id": "oem", "on": 2, "required": True, "match": "/9820772380/"}]
        answers = ["nope", "nope", "ref 9820772380"]
        r = scoring.score_facts(facts, answers)
        self.assertEqual(r["found"], ["oem"])
        self.assertEqual(r["missing"], [])

    def test_fact_present_in_wrong_turn_is_missing(self):
        facts = [{"id": "oem", "on": 2, "required": True, "match": "/9820772380/"}]
        answers = ["ref 9820772380", "nope", "nope"]
        self.assertEqual(scoring.score_facts(facts, answers)["missing"], ["oem"])

    def test_on_absent_searches_all_turns(self):
        facts = [{"id": "any", "required": True, "match": "/needle/"}]
        self.assertEqual(scoring.score_facts(facts, ["a", "needle", "c"])["found"], ["any"])

    def test_optional_facts_are_not_required(self):
        facts = [{"id": "used", "on": 0, "required": False, "match": "/39/"}]
        r = scoring.score_facts(facts, ["no price"])
        self.assertEqual(r["missing"], [])
        self.assertEqual(r["required"], 0)


class TestCheckForbidden(unittest.TestCase):
    def test_bare_assertion_is_a_violation(self):
        rules = [{"id": "ref-as-fact", "on": 0, "match": "/9831776780/",
                  "unless": "/non confirm|à vérifier/"}]
        self.assertEqual(scoring.check_forbidden(rules, ["la ref est 9831776780"]),
                         ["ref-as-fact"])

    def test_hedged_mention_is_not_a_violation(self):
        """The DS7 baseline names 9831776780 while flagging it unconfirmed."""
        rules = [{"id": "ref-as-fact", "on": 0, "match": "/9831776780/",
                  "unless": "/non confirm|à vérifier/"}]
        answers = ["La référence 9831776780 n'a pas pu être confirmée — à vérifier."]
        self.assertEqual(scoring.check_forbidden(rules, answers), [])

    def test_hedge_in_different_turn_is_a_violation(self):
        """When on is absent, each turn is checked individually. A hedge in turn 5
        does not whitewash an unhedged assertion in turn 0."""
        rules = [{"id": "ref-as-fact", "match": "/9831776780/",
                  "unless": "/non confirm|à vérifier/"}]
        answers = ["la ref est 9831776780", "a", "b", "c", "d", "non confirmé plus tard"]
        self.assertEqual(scoring.check_forbidden(rules, answers), ["ref-as-fact"])

    def test_hedge_in_same_turn_is_not_a_violation_without_on(self):
        """Without on, a hedge and assertion in the same turn is not a violation."""
        rules = [{"id": "ref-as-fact", "match": "/9831776780/",
                  "unless": "/non confirm|à vérifier/"}]
        answers = ["La référence 9831776780 n'a pas pu être confirmée — à vérifier."]
        self.assertEqual(scoring.check_forbidden(rules, answers), [])


class TestQualityGate(unittest.TestCase):
    def test_passes_when_all_required_found_and_nothing_forbidden(self):
        task = {"facts": [{"id": "a", "on": 0, "required": True, "match": "/ok/"}]}
        self.assertTrue(scoring.quality_gate(task, ["ok"])["quality_gate"])

    def test_fails_on_one_missing_required_fact(self):
        task = {"facts": [{"id": "a", "on": 0, "required": True, "match": "/ok/"}]}
        self.assertFalse(scoring.quality_gate(task, ["nope"])["quality_gate"])

    def test_fails_on_a_forbidden_hit_even_with_all_facts(self):
        task = {"facts": [{"id": "a", "on": 0, "required": True, "match": "/ok/"}],
                "forbidden": [{"id": "bad", "on": 0, "match": "/invented/"}]}
        r = scoring.quality_gate(task, ["ok and invented"])
        self.assertFalse(r["quality_gate"])
        self.assertEqual(r["forbidden_hits"], ["bad"])

    def test_returns_none_when_the_task_declares_nothing(self):
        self.assertIsNone(scoring.quality_gate({}, ["whatever"])["quality_gate"])


import bench


class TestTaskPrompts(unittest.TestCase):
    def test_single_prompt_becomes_a_one_element_list(self):
        self.assertEqual(bench.task_prompts({"prompt": "hello"}), ["hello"])

    def test_prompts_list_is_used_verbatim(self):
        self.assertEqual(bench.task_prompts({"prompts": ["a", "b"]}), ["a", "b"])

    def test_prompts_wins_over_prompt(self):
        self.assertEqual(bench.task_prompts({"prompt": "x", "prompts": ["a"]}), ["a"])

    def test_missing_both_raises(self):
        with self.assertRaises(KeyError):
            bench.task_prompts({})


class TestFetchCount(unittest.TestCase):
    def test_sums_leader_and_subagent_webfetch(self):
        m = {"leader_tools": {"WebFetch": 2, "Read": 9},
             "subagent_tools": {"web_agent": {"WebFetch": 5, "WebSearch": 3},
                                "summariser": {"WebFetch": 1}}}
        self.assertEqual(bench.fetch_count(m), 8)

    def test_zero_when_nothing_fetched(self):
        self.assertEqual(bench.fetch_count({"leader_tools": {}, "subagent_tools": {}}), 0)


class TestNoteUrl(unittest.TestCase):
    def test_records_http_urls_only(self):
        m = {"_urls": set()}
        bench._note_url(m, {"url": "https://example.com/a"})
        bench._note_url(m, {"url": "file:///etc/passwd"})
        bench._note_url(m, {"pattern": "not a url"})
        bench._note_url(m, None)
        self.assertEqual(m["_urls"], {"https://example.com/a"})

    def test_deduplicates(self):
        m = {"_urls": set()}
        bench._note_url(m, {"url": "https://example.com/a"})
        bench._note_url(m, {"url": "https://example.com/a"})
        self.assertEqual(len(m["_urls"]), 1)


import variants


class TestFindAgent(unittest.TestCase):
    def test_list_of_objects_shape(self):
        cfg = {"agents": [{"name": "leader"}, {"name": "web_agent", "max_instances": 10}]}
        self.assertEqual(variants.find_agent(cfg, "web_agent")["max_instances"], 10)

    def test_name_keyed_dict_shape(self):
        cfg = {"agents": {"web_agent": {"max_instances": 10}}}
        self.assertEqual(variants.find_agent(cfg, "web_agent")["max_instances"], 10)

    def test_unknown_agent_is_none(self):
        self.assertIsNone(variants.find_agent({"agents": []}, "nope"))


class TestApplyPatch(unittest.TestCase):
    def test_set_key_does_not_mutate_the_input(self):
        cfg = {"agents": [{"name": "web_agent", "max_instances": 10}]}
        out = variants.apply_patch(cfg, {"agent": "web_agent", "key": "max_instances", "value": 4})
        self.assertEqual(variants.find_agent(out, "web_agent")["max_instances"], 4)
        self.assertEqual(variants.find_agent(cfg, "web_agent")["max_instances"], 10)

    def test_remove_from_drops_a_list_entry(self):
        cfg = {"agents": [{"name": "web_agent", "tools": ["serper", "web", "ddg"]}]}
        out = variants.apply_patch(cfg, {"agent": "web_agent", "remove_from": "tools", "value": "web"})
        self.assertEqual(variants.find_agent(out, "web_agent")["tools"], ["serper", "ddg"])

    def test_remove_absent_entry_is_a_noop(self):
        cfg = {"agents": [{"name": "web_agent", "tools": ["serper"]}]}
        out = variants.apply_patch(cfg, {"agent": "web_agent", "remove_from": "tools", "value": "web"})
        self.assertEqual(variants.find_agent(out, "web_agent")["tools"], ["serper"])

    def test_unknown_agent_raises(self):
        with self.assertRaises(KeyError):
            variants.apply_patch({"agents": []}, {"agent": "ghost", "key": "x", "value": 1})


class TestSwitcherApplyResetsToBaseline(unittest.TestCase):
    """Pins the fix-round-1 defect: apply()'s old `touched` guard meant a
    no-patch variant (V0, the interleaved campaign's drift witness) never
    PUT anything, silently leaving whatever the PREVIOUS variant set still
    live. apply() must always PUT the computed config for every managed
    section, so apply(<no-patch variant>) is a genuine reset to baseline.

    Uses a fake HTTP layer (records PUT calls) instead of a live server —
    this must never touch a running omnis-server, which may have a
    benchmark campaign in flight against it.
    """

    def test_no_patch_variant_after_a_patched_one_still_puts_the_baseline(self):
        calls = []
        baseline_cfg = {"agents": [{"name": "web_agent", "max_instances": 10}]}

        def fake_api(method, base, path, token, body=None, timeout=60):
            if method == "GET":
                return {"name": "agent", "data": copy.deepcopy(baseline_cfg), "mtime": "t0"}
            if method == "PUT":
                calls.append((path, copy.deepcopy(body)))
                return {}
            if method == "POST":
                return {}
            raise AssertionError(f"unexpected method {method!r}")

        with mock.patch.object(variants, "api", fake_api):
            sw = variants.Switcher("http://example.invalid", "tok")
            sw.snapshot()

            sw.apply({"id": "V1", "patches": [
                {"agent": "web_agent", "key": "max_instances", "value": 4},
            ]})
            self.assertEqual(len(calls), 1, "V1 (a patched variant) must PUT once")

            # V0: the interleaved campaign's no-patch baseline/drift witness.
            sw.apply({"id": "V0", "patches": []})
            self.assertEqual(
                len(calls), 2,
                "apply() with an empty patch list must still PUT — this is the reset "
                "that keeps V0 witnesses honest in a time-interleaved campaign",
            )
            _, reset_body = calls[1]
            reset_agent = variants.find_agent(reset_body["data"], "web_agent")
            self.assertEqual(
                reset_agent["max_instances"], 10,
                "the V0 PUT body must equal the baseline, not the still-live V1 value",
            )


class TestNoteModelCacheBilling(unittest.TestCase):
    """note_model's cost estimate. `prompt_tokens` follows the OpenAI usage
    convention and already INCLUDES `cache_read_tokens` as a subset, not an
    addition. Billing the full `prompt_tokens` at the input price AND
    `cache_read_tokens` at the cache-read price double-charges the cached
    portion. Correct: the uncached remainder (prompt - cache_read, clamped at
    zero) pays the input price; cache_read pays the (usually much cheaper)
    cache-read price; output pays the output price."""

    def test_cache_hit_is_not_double_charged(self):
        """Real recorded record: 182311 prompt / 153089 cache-read (84% hit) /
        3052 output at ChapsVision Premium prices ($3.15/$15.75/$0.30 per M).
        The broken formula (prompt_tokens AND cache_read_tokens both billed in
        full) reads ~$0.668; the correct figure is ~$0.186."""
        m = bench.fresh()
        bench.note_model(m, {
            "agent": "web_agent",
            "prompt_tokens": 182311,
            "output_tokens": 3052,
            "cache_read_tokens": 153089,
            "in_price_per_m": 3.15,
            "out_price_per_m": 15.75,
            "cache_read_price_per_m": 0.30,
        })
        cost = m["models"]["web_agent"]["est_cost_usd"]
        self.assertAlmostEqual(cost, 0.186045, places=5)
        self.assertLess(cost, 0.4, "must not land anywhere near the broken $0.668 figure")

    def test_no_cache_path_is_unchanged(self):
        """cache_read_tokens == 0 (every web_agent record in practice today) must
        produce exactly the pre-fix formula: prompt*in + out*out — the
        backward-compatibility guarantee for the non-caching majority of records."""
        m = bench.fresh()
        bench.note_model(m, {
            "agent": "leader",
            "prompt_tokens": 50000,
            "output_tokens": 1200,
            "cache_read_tokens": 0,
            "in_price_per_m": 5.0,
            "out_price_per_m": 25.0,
            "cache_read_price_per_m": 0.5,
        })
        e = m["models"]["leader"]
        expected = round(50000 * 5.0 / 1e6 + 1200 * 25.0 / 1e6, 6)
        self.assertEqual(e["est_cost_usd"], expected)

    def test_accumulates_across_calls(self):
        """note_model is called once per model call and must SUM across calls,
        not overwrite — both the raw counters and the cost estimate."""
        m = bench.fresh()
        prices = {"in_price_per_m": 2.0, "out_price_per_m": 10.0, "cache_read_price_per_m": 0.5}
        bench.note_model(m, dict(agent="a", prompt_tokens=1000, output_tokens=100,
                                  cache_read_tokens=400, **prices))
        bench.note_model(m, dict(agent="a", prompt_tokens=2000, output_tokens=200,
                                  cache_read_tokens=1500, **prices))
        e = m["models"]["a"]
        self.assertEqual(e["prompt_tok"], 3000)
        self.assertEqual(e["cache_read_tok"], 1900)
        self.assertEqual(e["out_tok"], 300)
        self.assertEqual(e["calls"], 2)
        cost1 = (600 * 2.0 + 400 * 0.5 + 100 * 10.0) / 1e6
        cost2 = (500 * 2.0 + 1500 * 0.5 + 200 * 10.0) / 1e6
        self.assertAlmostEqual(e["est_cost_usd"], cost1 + cost2, places=6)

    def test_cache_read_over_prompt_tokens_is_clamped_not_negative(self):
        """Defensive: if a provider ever reports cache_read_tokens > prompt_tokens,
        (prompt - cache_read) must clamp at zero rather than produce a
        silently negative charge."""
        m = bench.fresh()
        bench.note_model(m, {
            "agent": "odd",
            "prompt_tokens": 100,
            "output_tokens": 10,
            "cache_read_tokens": 150,
            "in_price_per_m": 10.0,
            "out_price_per_m": 20.0,
            "cache_read_price_per_m": 1.0,
        })
        cost = m["models"]["odd"]["est_cost_usd"]
        self.assertGreaterEqual(cost, 0.0)
        self.assertAlmostEqual(cost, (150 * 1.0 + 10 * 20.0) / 1e6, places=6)


if __name__ == "__main__":
    unittest.main()
