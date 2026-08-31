#!/usr/bin/env python3
"""Unit tests for squad-bench pure logic. Run: python3 -m unittest discover -s squad-bench"""
import contextlib
import copy
import json
import os
import sys
import tempfile
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


import campaign


class TestInterleavedOrder(unittest.TestCase):
    def test_variants_alternate_within_each_repeat(self):
        self.assertEqual(campaign.interleaved_order(["V0", "V1", "V3"], 2),
                         ["V0", "V1", "V3", "V0", "V1", "V3"])

    def test_single_repeat_is_one_pass(self):
        self.assertEqual(campaign.interleaved_order(["V0", "V1"], 1), ["V0", "V1"])

    def test_zero_repeats_is_empty(self):
        self.assertEqual(campaign.interleaved_order(["V0"], 0), [])


class TestMedian(unittest.TestCase):
    def test_odd_length(self):
        self.assertEqual(campaign.median([3, 1, 2]), 2)

    def test_even_length_averages_the_middle(self):
        self.assertEqual(campaign.median([1, 2, 3, 4]), 2.5)

    def test_empty_is_none(self):
        self.assertIsNone(campaign.median([]))


class TestDriftOk(unittest.TestCase):
    def test_stable_witness_passes(self):
        first = [{"task": "t", "quality_gate": True, "total_cost_usd": 1.0}]
        last = [{"task": "t", "quality_gate": True, "total_cost_usd": 1.2}]
        ok, _ = campaign.drift_ok(first, last)
        self.assertTrue(ok)

    def test_one_task_regressing_voids_the_campaign(self):
        """A single canary regression must void it; the others still passing
        must not mask it."""
        first = [{"task": "web-canary", "quality_gate": True, "total_cost_usd": 1.0},
                 {"task": "web-lookup", "quality_gate": True, "total_cost_usd": 1.0}]
        last = [{"task": "web-canary", "quality_gate": False, "total_cost_usd": 1.0},
                {"task": "web-lookup", "quality_gate": True, "total_cost_usd": 1.0}]
        ok, why = campaign.drift_ok(first, last)
        self.assertFalse(ok)
        self.assertIn("web-canary", why)

    def test_cost_doubling_in_the_witness_voids_the_campaign(self):
        first = [{"task": "t", "quality_gate": True, "total_cost_usd": 1.0}]
        last = [{"task": "t", "quality_gate": True, "total_cost_usd": 2.5}]
        ok, why = campaign.drift_ok(first, last)
        self.assertFalse(ok)
        self.assertIn("cost", why.lower())

    def test_observation_count_collapse_voids_a_non_gating_task(self):
        """web-deep-ds7 declares only OPTIONAL facts, so quality_gate is
        unconditionally True and can never itself flip False -- the
        observation count (facts.optional_found) is the only signal
        available for it. Measured on this exact task: a healthy answer
        yields 5 observations; three separately captured degraded-search
        runs yielded 1, 2, and 3 (see tasks-web.json's web-deep-ds7 notes).
        A drop from 5 to 2 is well past the >2x threshold."""
        first = [{"task": "web-deep-ds7", "quality_gate": True, "total_cost_usd": 1.0,
                  "facts": {"required": 0, "optional_found": ["a", "b", "c", "d", "e"]}}]
        last = [{"task": "web-deep-ds7", "quality_gate": True, "total_cost_usd": 1.0,
                 "facts": {"required": 0, "optional_found": ["a", "b"]}}]
        ok, why = campaign.drift_ok(first, last)
        self.assertFalse(ok)
        self.assertIn("web-deep-ds7", why)
        self.assertIn("observation", why.lower())

    def test_observation_count_dropping_by_less_than_half_is_not_flagged(self):
        """Measured calib run3 on web-deep-ds7: 3 of 5 observations survived
        under degraded search and that run was still judged acceptable --
        a drop that stays above the >2x threshold must not void."""
        first = [{"task": "web-deep-ds7", "quality_gate": True, "total_cost_usd": 1.0,
                  "facts": {"required": 0, "optional_found": ["a", "b", "c", "d", "e"]}}]
        last = [{"task": "web-deep-ds7", "quality_gate": True, "total_cost_usd": 1.0,
                 "facts": {"required": 0, "optional_found": ["a", "b", "c"]}}]
        ok, _ = campaign.drift_ok(first, last)
        self.assertTrue(ok)

    def test_pooled_median_would_have_missed_a_single_task_cost_blowup(self):
        """This pins the CRITICAL fix: with 3 witness records, a pooled
        median of [0.1, 0.2, 0.5] -> [0.1, 0.2, 3.0] is UNCHANGED (0.2 both
        times) even though one task's cost went up 6x -- the median simply
        picks the middle-ranked value and never looks at the outlier. The
        per-task check must catch it regardless of what the other two tasks
        did."""
        first = [
            {"task": "web-canary", "quality_gate": True, "total_cost_usd": 0.1},
            {"task": "web-lookup", "quality_gate": True, "total_cost_usd": 0.2},
            {"task": "web-deep-ds7", "quality_gate": True, "total_cost_usd": 0.5,
             "facts": {"required": 0, "optional_found": ["a", "b", "c", "d", "e"]}},
        ]
        last = [
            {"task": "web-canary", "quality_gate": True, "total_cost_usd": 0.1},
            {"task": "web-lookup", "quality_gate": True, "total_cost_usd": 0.2},
            {"task": "web-deep-ds7", "quality_gate": True, "total_cost_usd": 3.0,
             "facts": {"required": 0, "optional_found": ["a", "b", "c", "d", "e"]}},
        ]
        # Confirm the premise: pooling really would have hidden this.
        pooled_first = campaign.median([r["total_cost_usd"] for r in first])
        pooled_last = campaign.median([r["total_cost_usd"] for r in last])
        self.assertEqual(pooled_first, pooled_last, "the pooled median must look unchanged")

        ok, why = campaign.drift_ok(first, last)
        self.assertFalse(ok)
        self.assertIn("web-deep-ds7", why)
        self.assertIn("cost", why.lower())

    def test_a_task_missing_from_one_witness_pass_is_skipped_not_raised(self):
        first = [{"task": "web-canary", "quality_gate": True, "total_cost_usd": 0.1},
                 {"task": "web-lookup", "quality_gate": True, "total_cost_usd": 0.2}]
        last = [{"task": "web-canary", "quality_gate": True, "total_cost_usd": 0.1}]
        ok, _ = campaign.drift_ok(first, last)
        self.assertTrue(ok)


class TestSearchDegradation(unittest.TestCase):
    """Post-hoc degradation detector (replaces a pre-flight DuckDuckGo probe --
    the fleet now uses a paid Serper backend, so probing DDG directly would
    measure the wrong thing). A record is flagged `search_degraded` when its
    `subagent_errors` carry a search-failure marker, or its `fetches` count is
    anomalous versus its peers **for the same task AND the same variant** in
    the campaign (fetch counts are only comparable within one task -- a
    lookup task legitimately fetches far less than a deep multi-turn one --
    and within one variant -- a variant that fetches far fewer times BY
    DESIGN, e.g. one that delegates fetching to collapse an F^2 term, is not
    degraded, it is doing its job; comparing it against a different
    variant's count would flag exactly the effect a campaign exists to
    measure)."""

    def test_deadline_exceeded_marker_flags_degraded(self):
        r = {"task": "t", "fetches": 5,
             "subagent_errors": [{"agent": "web_agent", "detail": "context deadline exceeded"}]}
        campaign.mark_search_degraded(r, [r])
        self.assertTrue(r["search_degraded"])
        self.assertIn("deadline exceeded", r["degraded_reason"])

    def test_marker_match_is_case_insensitive(self):
        r = {"task": "t", "fetches": 5,
             "subagent_errors": [{"agent": "web_agent", "detail": "HTTP 429 RATE LIMIT hit"}]}
        campaign.mark_search_degraded(r, [r])
        self.assertTrue(r["search_degraded"])

    def test_no_results_marker_flags_degraded(self):
        r = {"task": "t", "fetches": 0,
             "subagent_errors": [{"agent": "web_agent", "detail": "search returned no results"}]}
        campaign.mark_search_degraded(r, [r])
        self.assertTrue(r["search_degraded"])

    def test_clean_record_with_typical_fetches_is_not_degraded(self):
        recs = [{"task": "t", "fetches": n, "subagent_errors": []} for n in (40, 45, 50, 55)]
        for r in recs:
            campaign.mark_search_degraded(r, recs)
        self.assertTrue(all(not r["search_degraded"] for r in recs))
        self.assertTrue(all(r["degraded_reason"] == "" for r in recs))

    def test_fetch_collapse_versus_peers_flags_degraded(self):
        recs = [{"task": "t", "fetches": n, "subagent_errors": []} for n in (40, 45, 50)]
        collapsed = {"task": "t", "fetches": 1, "subagent_errors": []}
        recs.append(collapsed)
        campaign.mark_search_degraded(collapsed, recs)
        self.assertTrue(collapsed["search_degraded"])
        self.assertIn("fetches", collapsed["degraded_reason"])

    def test_fetch_explosion_versus_peers_flags_degraded(self):
        recs = [{"task": "t", "fetches": n, "subagent_errors": []} for n in (40, 45, 50)]
        exploded = {"task": "t", "fetches": 300, "subagent_errors": []}
        recs.append(exploded)
        campaign.mark_search_degraded(exploded, recs)
        self.assertTrue(exploded["search_degraded"])

    def test_ordinary_1_5x_spread_between_identical_configs_is_not_flagged(self):
        """Measured fact: two runs of the IDENTICAL configuration differed by
        1.5x in fetches. That must not, by itself, read as degradation."""
        a = {"task": "t", "fetches": 40, "subagent_errors": []}
        b = {"task": "t", "fetches": 60, "subagent_errors": []}
        c = {"task": "t", "fetches": 50, "subagent_errors": []}
        for r in (a, b, c):
            campaign.mark_search_degraded(r, [a, b, c])
        self.assertFalse(a["search_degraded"])
        self.assertFalse(b["search_degraded"])
        self.assertFalse(c["search_degraded"])

    def test_different_tasks_are_not_cross_compared(self):
        """A lookup task's low fetch count must not be judged anomalous
        against a deep task's much higher one just because they ran in the
        same campaign."""
        lookup = {"task": "web-lookup", "fetches": 3, "subagent_errors": []}
        deep = {"task": "web-deep-ds7", "fetches": 80, "subagent_errors": []}
        campaign.mark_search_degraded(lookup, [lookup, deep])
        campaign.mark_search_degraded(deep, [lookup, deep])
        self.assertFalse(lookup["search_degraded"])
        self.assertFalse(deep["search_degraded"])

    def test_different_variants_of_the_same_task_are_not_cross_compared(self):
        """The design bug this pins: a variant that legitimately fetches far
        FEWER times than the baseline, by design (e.g. it delegates fetching
        to a one-step sub-agent specifically to collapse an F^2 term), must
        not be flagged just because it looks anomalous next to a DIFFERENT
        variant's count -- that would penalize exactly the effect a campaign
        exists to measure. V0 has enough same-variant peers to judge itself;
        V3 (only one sample here) has none of its own and so is left alone,
        rather than being judged against V0's much higher count."""
        v0_recs = [{"task": "t", "variant": "V0", "fetches": n, "subagent_errors": []}
                   for n in (78, 80, 82)]
        v3_rec = {"task": "t", "variant": "V3", "fetches": 5, "subagent_errors": []}
        all_recs = v0_recs + [v3_rec]
        for r in all_recs:
            campaign.mark_search_degraded(r, all_recs)
        self.assertFalse(v3_rec["search_degraded"],
                          "V3 fetching far less than V0 is a variant effect, not degradation")
        self.assertTrue(all(not r["search_degraded"] for r in v0_recs))

    def test_no_same_task_peers_never_flags_on_fetch_count_alone(self):
        r = {"task": "t", "fetches": 500, "subagent_errors": []}
        campaign.mark_search_degraded(r, [r])
        self.assertFalse(r["search_degraded"])

    def test_missing_fetches_and_no_errors_is_not_degraded(self):
        r = {"task": "t", "subagent_errors": []}
        campaign.mark_search_degraded(r, [r])
        self.assertFalse(r["search_degraded"])

    def test_both_signals_are_combined_into_one_reason(self):
        recs = [{"task": "t", "fetches": n, "subagent_errors": []} for n in (40, 45, 50)]
        bad = {"task": "t", "fetches": 0,
               "subagent_errors": [{"agent": "web_agent", "detail": "timeout after 30s"}]}
        recs.append(bad)
        campaign.mark_search_degraded(bad, recs)
        self.assertTrue(bad["search_degraded"])
        self.assertIn("timeout", bad["degraded_reason"])
        self.assertIn("fetches", bad["degraded_reason"])


class TestSpread(unittest.TestCase):
    """Two runs of the IDENTICAL configuration were observed to differ 1.85x
    in cost ($0.908 vs $1.682). A bare median hides that -- spread() reports
    the range beside it."""

    def test_computes_median_min_max_and_count(self):
        recs = [{"total_cost_usd": 0.908}, {"total_cost_usd": 1.682}, {"total_cost_usd": 1.2}]
        s = campaign.spread(recs, "total_cost_usd")
        self.assertEqual(s["median"], 1.2)
        self.assertEqual(s["min"], 0.908)
        self.assertEqual(s["max"], 1.682)
        self.assertEqual(s["n"], 3)

    def test_ignores_records_missing_the_key(self):
        recs = [{"total_cost_usd": 1.0}, {}, {"total_cost_usd": 3.0}]
        s = campaign.spread(recs, "total_cost_usd")
        self.assertEqual(s["n"], 2)
        self.assertEqual(s["median"], 2.0)
        self.assertEqual(s["min"], 1.0)
        self.assertEqual(s["max"], 3.0)

    def test_empty_list_is_all_none_and_zero_count(self):
        s = campaign.spread([], "total_cost_usd")
        self.assertIsNone(s["median"])
        self.assertIsNone(s["min"])
        self.assertIsNone(s["max"])
        self.assertEqual(s["n"], 0)

    def test_defaults_to_total_cost_usd(self):
        recs = [{"total_cost_usd": 2.0}, {"total_cost_usd": 4.0}]
        self.assertEqual(campaign.spread(recs)["median"], 3.0)


class TestCampaignSummary(unittest.TestCase):
    """Per-variant median/range/count, with search-degraded runs excluded from
    the numbers but still counted (so the exclusion itself is visible)."""

    def test_groups_by_variant_in_first_seen_order(self):
        recs = [
            {"variant": "V0", "total_cost_usd": 1.0, "search_degraded": False},
            {"variant": "V1", "total_cost_usd": 0.5, "search_degraded": False},
            {"variant": "V0", "total_cost_usd": 1.2, "search_degraded": False},
        ]
        out = campaign.campaign_summary(recs)
        self.assertEqual([vid for vid, _ in out], ["V0", "V1"])
        v0 = dict(out)["V0"]
        self.assertEqual(v0["n"], 2)
        self.assertEqual(v0["total"], 2)
        self.assertEqual(v0["excluded"], 0)
        self.assertEqual(v0["median"], 1.1)

    def test_degraded_runs_are_excluded_from_the_median_but_counted(self):
        recs = [
            {"variant": "V0", "total_cost_usd": 1.0, "search_degraded": False},
            {"variant": "V0", "total_cost_usd": 1.0, "search_degraded": False},
            {"variant": "V0", "total_cost_usd": 99.0, "search_degraded": True},
        ]
        out = dict(campaign.campaign_summary(recs))
        self.assertEqual(out["V0"]["n"], 2)
        self.assertEqual(out["V0"]["total"], 3)
        self.assertEqual(out["V0"]["excluded"], 1)
        self.assertEqual(out["V0"]["median"], 1.0)
        self.assertEqual(out["V0"]["max"], 1.0, "the degraded outlier must not skew the range")

    def test_records_without_a_variant_are_ignored(self):
        recs = [{"total_cost_usd": 1.0}, {"variant": "V0", "total_cost_usd": 2.0}]
        out = dict(campaign.campaign_summary(recs))
        self.assertEqual(list(out.keys()), ["V0"])

    def test_all_degraded_variant_reports_zero_clean_runs(self):
        recs = [{"variant": "V1", "total_cost_usd": 5.0, "search_degraded": True}]
        out = dict(campaign.campaign_summary(recs))
        self.assertEqual(out["V1"]["n"], 0)
        self.assertEqual(out["V1"]["total"], 1)
        self.assertIsNone(out["V1"]["median"])


class _FakeSwitcher:
    """Records apply/verify/revert calls against an in-memory catalog --
    NEVER touches a real server or config. Installed in place of
    `variants.Switcher` for the duration of one `TestCampaignMain` test."""

    def __init__(self, verify_fails_for=(), revert_mismatch=None):
        self.applied = []
        self.verified = []
        self.reverted = False
        self._verify_fails_for = set(verify_fails_for)
        self._revert_mismatch = list(revert_mismatch or [])

    def snapshot(self):
        return {}

    def apply(self, variant):
        self.applied.append(variant.get("id"))

    def verify(self, variant):
        vid = variant.get("id")
        self.verified.append(vid)
        return ["mismatch"] if vid in self._verify_fails_for else []

    def revert(self):
        self.reverted = True
        return list(self._revert_mismatch)


def _fake_squads_api(method, base, path, token, body=None, timeout=60):
    if path == "/api/squads":
        return {"squads": [{"name": "x", "leader": "leader", "members": ["agent"]}]}
    return {}


def _fake_campaign_record(task_id, total_cost_usd=0.1, quality_gate=True, optional_found=None):
    """A minimally-complete bench.run_task()-shaped record: enough for
    bench.summarize() and campaign.py's own drift/degradation/summary logic
    to run without crashing, with no real server involved."""
    m = bench.fresh()
    m.update({
        "task": task_id, "squad": "x", "status": "done", "wall_ms": 100,
        "redispatches": 0, "answer": "", "answers": [], "correct": None,
        "total_cost_usd": total_cost_usd, "quality_gate": quality_gate,
        "facts": {"found": [], "missing": [], "required": 0,
                  "optional_found": list(optional_found or [])},
        "forbidden_hits": [], "distinct_urls": 0, "fetches": 0,
        "facts_per_fetch": None,
    })
    for k in ("_answer_parts", "_seq", "_urls"):
        m.pop(k, None)
    return m


_FAKE_CATALOG = {
    "V0": {"id": "V0", "label": "baseline", "patches": []},
    "V1": {"id": "V1", "label": "variant one", "patches": []},
}


class TestCampaignMain(unittest.TestCase):
    """Exercises campaign.main()'s control flow -- the revert guarantee, the
    verify-abort, and the exit codes -- end-to-end with FAKES standing in
    for `variants.Switcher` and `bench.run_task`. NEVER touches a live
    server or applies a real config change: a real campaign may be queued
    against the running server and must not be disturbed by these tests."""

    def setUp(self):
        fd, self.tasks_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump({"tasks": [{"id": "t1", "squad": "x", "prompt": "hi"}]}, f)

    def tearDown(self):
        os.remove(self.tasks_path)

    def _run_main(self, fake_sw, fake_run_task, argv_extra=()):
        argv = ["campaign.py", "--tasks", self.tasks_path, "--repeat", "1", *argv_extra]
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(variants, "Switcher",
                                                   lambda base, token: fake_sw))
            stack.enter_context(mock.patch.object(variants, "load_variants",
                                                   lambda path: _FAKE_CATALOG))
            stack.enter_context(mock.patch.object(bench, "api", _fake_squads_api))
            stack.enter_context(mock.patch.object(bench, "run_task", fake_run_task))
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            campaign.main()

    def test_a_failing_verify_aborts_before_running_the_variants_tasks(self):
        calls = []

        def fake_run_task(base, token, task, agents, deadline, keep, cwd_override):
            calls.append(task["id"])
            return _fake_campaign_record(task["id"])

        fake_sw = _FakeSwitcher(verify_fails_for={"V1"})
        with self.assertRaises(SystemExit) as cm:
            self._run_main(fake_sw, fake_run_task, argv_extra=["--variants", "V1"])
        self.assertIn("did not apply cleanly", str(cm.exception.code))
        # Only the V0 opening witness's task ran; V1's own tasks were never
        # attempted because verify() failed first.
        self.assertEqual(calls, ["t1"])
        self.assertTrue(fake_sw.reverted, "the finally block must still revert")

    def test_revert_runs_even_when_the_campaign_body_raises(self):
        def raising_run_task(base, token, task, agents, deadline, keep, cwd_override):
            raise RuntimeError("boom")

        fake_sw = _FakeSwitcher()
        with self.assertRaises(RuntimeError):
            self._run_main(fake_sw, raising_run_task)
        self.assertTrue(fake_sw.reverted, "revert must run even on an unexpected crash")

    def test_revert_mismatch_produces_a_distinct_nonzero_exit_code(self):
        def fake_run_task(base, token, task, agents, deadline, keep, cwd_override):
            return _fake_campaign_record(task["id"])

        fake_sw = _FakeSwitcher(
            revert_mismatch=["agent.web_agent.max_instances is 4, expected 10"])
        with self.assertRaises(SystemExit) as cm:
            self._run_main(fake_sw, fake_run_task)
        self.assertEqual(cm.exception.code, 3,
                          "a failed revert must exit with a code distinct from drift-void (2)")
        self.assertTrue(fake_sw.reverted)

    def test_successful_campaign_with_stable_witnesses_exits_zero(self):
        def fake_run_task(base, token, task, agents, deadline, keep, cwd_override):
            return _fake_campaign_record(task["id"], total_cost_usd=0.1, quality_gate=True)

        fake_sw = _FakeSwitcher()
        with self.assertRaises(SystemExit) as cm:
            self._run_main(fake_sw, fake_run_task)
        self.assertEqual(cm.exception.code, 0)
        self.assertTrue(fake_sw.reverted)

    def test_observation_count_collapse_voids_the_campaign_via_main(self):
        """End-to-end proof the CRITICAL fix is wired into main(), not just
        into drift_ok() in isolation: the opening witness sees 5 optional
        facts, the closing witness sees 1, and the campaign must exit 2."""
        call_count = {"n": 0}

        def fake_run_task(base, token, task, agents, deadline, keep, cwd_override):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _fake_campaign_record(task["id"], optional_found=["a", "b", "c", "d", "e"])
            return _fake_campaign_record(task["id"], optional_found=["a"])

        fake_sw = _FakeSwitcher()
        with self.assertRaises(SystemExit) as cm:
            self._run_main(fake_sw, fake_run_task)
        self.assertEqual(cm.exception.code, 2)
        self.assertTrue(fake_sw.reverted)


class TestFetchAnomalyVolumeFloor(unittest.TestCase):
    """`fetches_anomalous`'s ratio test only means something once the peer
    group has done enough real work for a median to be a meaningful quantity.

    OBSERVED FAILURE from a real campaign: three `web-lookup` runs were
    excluded as `search_degraded` with reasons `fetches=3 vs peer median 0.5`,
    `fetches=0 vs peer median 1.0`, and `fetches=0 vs peer median 2.0`. On a
    task that legitimately makes 0-3 fetches, a swing of one or two fetches
    is meaningless noise, and a "peer median" of 0.5 is not a meaningful
    quantity at all -- the ratio test blows up at these scales for any
    plausible fetch count. So the ratio test now requires the peer median to
    clear `FETCH_ANOMALY_MIN_PEER_MEDIAN` (5) before it applies at all; below
    that floor only the (volume-independent) subagent_errors signal can flag
    a run. 5 is picked because every real false-positive peer median observed
    (0.5, 1.0, 2.0) sits well under it, while the one confirmed genuine
    anomaly on record (21 fetches vs a peer median of 108) sits two orders of
    magnitude above it -- there is a wide, unambiguous gap between "noise on a
    low-fetch task" and "a real collapse/explosion on a high-fetch task" for
    5 to sit inside."""

    def test_low_volume_peer_median_no_longer_flags(self):
        """Reproduces the three real false positives verbatim: peer medians
        0.5, 1.0, 2.0 (all < the floor) must never flag on fetch count alone,
        regardless of how large the ratio to the record's own count is."""
        cases = [
            # (record fetches, peer fetches) -> real observed peer median
            (3, [0, 1]),      # peer median 0.5
            (0, [1, 1]),      # peer median 1.0
            (0, [1, 3]),      # peer median 2.0
        ]
        for fetches, peer_fetches in cases:
            with self.subTest(fetches=fetches, peers=peer_fetches):
                record = {"task": "web-lookup", "fetches": fetches, "subagent_errors": []}
                peers = [{"task": "web-lookup", "fetches": f, "subagent_errors": []}
                         for f in peer_fetches]
                all_recs = [record] + peers
                campaign.mark_search_degraded(record, all_recs)
                self.assertFalse(
                    record["search_degraded"],
                    f"fetches={fetches} vs low-volume peers {peer_fetches} must not flag")
                self.assertEqual(record["degraded_reason"], "")

    def test_genuine_high_volume_anomaly_still_flags(self):
        """Real data: 21 fetches vs a peer median of 108 (well above the
        floor) is a genuine collapse and must still be caught."""
        peers = [{"task": "web-deep-ds7", "fetches": n, "subagent_errors": []}
                 for n in (100, 108, 116)]
        collapsed = {"task": "web-deep-ds7", "fetches": 21, "subagent_errors": []}
        all_recs = peers + [collapsed]
        campaign.mark_search_degraded(collapsed, all_recs)
        self.assertTrue(collapsed["search_degraded"])
        self.assertIn("fetches", collapsed["degraded_reason"])
        self.assertIn("108", collapsed["degraded_reason"])

    def test_subagent_error_path_still_flags_at_any_volume(self):
        """The volume floor must gate ONLY the fetch-count ratio test. A
        search-backend failure is a real signal regardless of how few fetches
        were made, and regardless of whether there are any same-task/variant
        peers at all -- this must not be weakened by the floor."""
        # No peers at all.
        lone = {"task": "web-lookup", "fetches": 0,
                "subagent_errors": [{"agent": "web_agent", "detail": "context deadline exceeded"}]}
        campaign.mark_search_degraded(lone, [lone])
        self.assertTrue(lone["search_degraded"])
        self.assertIn("deadline exceeded", lone["degraded_reason"])

        # Low-volume peers (below the floor) alongside an error marker.
        peers = [{"task": "web-lookup", "fetches": f, "subagent_errors": []} for f in (0, 1)]
        erroring = {"task": "web-lookup", "fetches": 0,
                    "subagent_errors": [{"agent": "web_agent", "detail": "rate limit hit"}]}
        all_recs = peers + [erroring]
        campaign.mark_search_degraded(erroring, all_recs)
        self.assertTrue(erroring["search_degraded"])
        self.assertIn("rate limit", erroring["degraded_reason"])
        # And the fetch-count half must not have piggybacked onto the reason
        # (the low peer median is below the floor, so it contributes nothing).
        self.assertNotIn("fetches=", erroring["degraded_reason"])


if __name__ == "__main__":
    unittest.main()
