#!/usr/bin/env python3
"""Tests for budget. Run: python3 -m unittest squad-bench/test_budget.py"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import budget


class BudgetTest(unittest.TestCase):
    def test_over_ratio_waits_for_second_task(self):
        self.assertFalse(budget.over_ratio([1], [5]))
        self.assertTrue(budget.over_ratio([1, 1], [1, 2.5]))
        self.assertFalse(budget.over_ratio([1, 1], [1, 2]))  # exactly 1.5x does not exceed it

    def test_over_ratio_compares_same_number_of_tasks(self):
        # the arm has run 2 tasks, the reference 4: compare the first 2 only
        self.assertTrue(budget.over_ratio([1, 1, 10, 10], [2, 2]))

    def test_spent_sums_ledger(self):
        p = Path(tempfile.mkdtemp()) / "l.jsonl"
        p.write_text(json.dumps({"step": "a", "usd": 1.5}) + "\n" + json.dumps({"step": "b", "usd": 2.25}) + "\n")
        self.assertAlmostEqual(budget.spent(p), 3.75)

    def test_record_costs_read_in_order(self):
        p = Path(tempfile.mkdtemp()) / "r.jsonl"
        p.write_text("\n".join(json.dumps({"task": t, "total_cost_usd": c}) for t, c in [("a", 0.5), ("b", 1.0)]) + "\n")
        self.assertEqual(budget.record_costs(p), [0.5, 1.0])


if __name__ == "__main__":
    unittest.main()
