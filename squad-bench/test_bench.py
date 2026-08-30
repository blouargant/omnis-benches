#!/usr/bin/env python3
"""Unit tests for squad-bench pure logic. Run: python3 -m unittest discover -s squad-bench"""
import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
