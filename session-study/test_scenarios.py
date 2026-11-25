#!/usr/bin/env python3
"""Tests for scenarios. Run: python3 -m unittest discover -s session-study"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scenarios
import study

SRC = "Compare Acme Corp's cluster at gw.acme.example, see /home/bob/notes.md, budget 48000. Mail bob@acme.example."
REPLY = json.dumps({"prompts": ["Compare two clusters"], "kind": "web",
                    "rubric": {"pass": ["names both clusters"], "failure": "repeats the same search"}})


def draft(prompt, **extra):
    d = {"id": "ss-1", "squad": "knowledge", "prompt": prompt, "rubric": {"pass": ["x"], "failure": ""}}
    d.update(extra)
    return d


class LeaksTest(unittest.TestCase):
    def test_leaks_finds_names_paths_hosts_numbers(self):
        self.assertEqual(scenarios.leaks(SRC, draft("Compare Acme's cluster, budget 48000")), ["48000", "Acme"])
        self.assertEqual(scenarios.leaks(SRC, draft("Ask bob@acme.example or read /home/bob/notes.md on gw.acme.example")),
                         # "Acme" too: the name is still readable inside the host and the address
                         ["/home/bob/notes.md", "Acme", "bob@acme.example", "gw.acme.example"])

    def test_leaks_ignores_sentence_starts_and_common_tech_words(self):
        src = "Compare Kubernetes and Python on a GPU. Explain why. In 2026 it matters."
        self.assertEqual(scenarios.leaks(src, draft("Compare Kubernetes with Python on one GPU. Explain it for 2026.")), [])

    def test_leaks_respects_extra_allowed_tokens(self):
        self.assertEqual(scenarios.leaks(SRC, draft("About Acme"), allowed={"acme"}), [])

    def test_leaks_looks_into_files_and_rubric(self):
        self.assertEqual(scenarios.leaks(SRC, draft("Q", files={"a.txt": "owner: Acme"})), ["Acme"])
        self.assertEqual(scenarios.leaks(SRC, draft("Q", rubric={"pass": ["mentions 48000"], "failure": ""})), ["48000"])
        self.assertEqual(scenarios.leaks(SRC, {"id": "x", "prompts": ["one", "about Corp"], "rubric": {}}), ["Corp"])

    def test_no_whole_word_no_leak(self):
        self.assertEqual(scenarios.leaks("Ask Ann about it", draft("Announce the result")), [])


class DraftTest(unittest.TestCase):
    def test_parse_draft_shapes_one_or_several_requests(self):
        one = scenarios.parse_draft(REPLY, "ss-1", "knowledge")
        self.assertEqual(one, {"id": "ss-1", "squad": "knowledge", "kind": "web", "prompt": "Compare two clusters",
                               "rubric": {"pass": ["names both clusters"], "failure": "repeats the same search"}})
        many = scenarios.parse_draft(json.dumps({"prompts": ["a", "b"], "rubric": {"pass": ["x"], "failure": "f"},
                                                 "files": {"n.md": "text"}}), "ss-2", "system")
        self.assertEqual(many["prompts"], ["a", "b"])
        self.assertNotIn("prompt", many)
        self.assertEqual(many["files"], {"n.md": "text"})

    def test_parse_draft_requires_request_and_pass_criteria(self):
        for bad in ({"prompts": [], "rubric": {"pass": ["x"], "failure": "f"}},
                    {"prompts": ["  "], "rubric": {"pass": ["x"], "failure": "f"}},
                    {"prompts": ["q"], "rubric": {"pass": [], "failure": "f"}},
                    {"prompts": ["q"]},
                    {"prompts": ["q"], "rubric": {"pass": ["x"], "failure": ""}}):
            with self.assertRaises(ValueError, msg=bad):
                scenarios.parse_draft(json.dumps(bad), "ss-1", "knowledge")

    def test_control_must_have_empty_failure(self):
        ok = scenarios.parse_draft(json.dumps({"prompts": ["q"], "rubric": {"pass": ["x"], "failure": ""}}), "ss-c1", "k")
        self.assertEqual(ok["rubric"]["failure"], "")
        with self.assertRaises(ValueError):
            scenarios.parse_draft(REPLY, "ss-c1", "knowledge")

    def test_draft_prompt_fences_the_session_and_carries_the_users_note(self):
        t = {"user_text": "Q-TEXT", "reply": "R", "outline": "o()", "earlier_user_texts": ["EARLIER"]}
        system, user = scenarios.draft_prompt(t, ["EARLIER"], "search loop", "expected one search", False)
        self.assertIn("<<<BEGIN SESSION>>>", user)
        for part in ("Q-TEXT", "EARLIER", "search loop", "expected one search"):
            self.assertIn(part, user)
        self.assertIn("data", system.lower())

    def test_draft_skips_open_and_unsure_cards(self):
        turns = {"s#%d" % i: {"turn_id": "s#%d" % i, "squad": "knowledge" if i < 6 else "system",
                              "user_text": "q%d" % i, "reply": "r", "outline": "", "earlier_user_texts": []}
                 for i in range(8)}
        cards = [{"card": "c%02d" % (i + 1), "turn_id": "s#%d" % i, "why": "signal"} for i in range(8)]
        verdicts = {"c01": {"failure": "yes", "kind": "loop", "note": ""}, "c02": {"failure": "yes", "kind": "", "note": ""},
                    "c03": {"failure": "no", "kind": "", "note": ""}, "c07": {"failure": "no", "kind": "", "note": ""},
                    "c08": {"failure": "no", "kind": "", "note": ""}, "c05": {"failure": "no", "kind": "", "note": ""}}
        asked = []

        def call(model, system, user, timeout=300):
            asked.append(user)
            control = "CONTROL" in user
            return json.dumps({"prompts": ["rewritten"], "rubric": {"pass": ["x"], "failure": "" if control else "f"}}), {}

        drafts, sources, errors = scenarios.run_draft(cards, verdicts, turns, "m", call=call)
        self.assertEqual([d["id"] for d in drafts], ["ss-1", "ss-2", "ss-c1", "ss-c2"])
        self.assertEqual(sources, {"ss-1": "s#0", "ss-2": "s#1", "ss-c1": "s#2", "ss-c2": "s#4"})
        self.assertEqual(errors, [])
        self.assertEqual(len(asked), 4)

    def test_draft_ignores_a_card_whose_session_was_deleted(self):
        cards = [{"card": "c01", "turn_id": "gone#1", "why": "signal"}]
        verdicts = {"c01": {"failure": "yes", "kind": "", "note": ""}}
        drafts, sources, errors = scenarios.run_draft(cards, verdicts, {}, "m", call=lambda *a, **k: (REPLY, {}))
        self.assertEqual((drafts, sources), ([], {}))
        self.assertEqual(len(errors), 1)
        self.assertIn("c01", errors[0])

    def test_draft_reports_a_bad_reply_and_goes_on(self):
        turns = {"s#0": {"turn_id": "s#0", "squad": "k", "user_text": "q", "reply": "", "outline": ""},
                 "s#1": {"turn_id": "s#1", "squad": "k", "user_text": "q", "reply": "", "outline": ""}}
        cards = [{"card": "c01", "turn_id": "s#0", "why": "signal"}, {"card": "c02", "turn_id": "s#1", "why": "signal"}]
        verdicts = {"c01": {"failure": "yes", "kind": "", "note": ""}, "c02": {"failure": "yes", "kind": "", "note": ""}}
        replies = iter(["nope", REPLY])
        drafts, sources, errors = scenarios.run_draft(cards, verdicts, turns, "m", call=lambda *a, **k: (next(replies), {}))
        self.assertEqual([d["id"] for d in drafts], ["ss-2"])
        self.assertEqual(len(errors), 1)
        self.assertIn("ss-1", errors[0])


class AcceptTest(unittest.TestCase):
    def test_accept_refuses_a_leaking_draft(self):
        drafts = [draft("About Acme"), dict(draft("Clean"), id="ss-2")]
        texts = {"ss-1": SRC, "ss-2": SRC}
        with self.assertRaises(ValueError) as cm:
            scenarios.accept(drafts, texts, ["ss-1", "ss-2"])
        self.assertIn("Acme", str(cm.exception))
        self.assertEqual([d["id"] for d in scenarios.accept(drafts, texts, ["ss-2"])], ["ss-2"])
        with self.assertRaises(ValueError):
            scenarios.accept(drafts, texts, ["ss-9"])

    def test_scan_keeps_earlier_user_messages(self):
        sess = [{"id": "s", "squad": "k", "skills": [], "turns": [
            {"user_text": "first", "assistant_text": "a"},
            {"user_text": "second", "assistant_text": "a", "tools": [{"name": "Read", "args": {}, "result": "ok"}]}]}]
        rows = study.scan_turns(sess)
        self.assertEqual(rows[0]["earlier_user_texts"], ["first"])


if __name__ == "__main__":
    unittest.main()
