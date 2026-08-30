#!/usr/bin/env python3
"""Deterministic answer scoring for squad-bench — layer 1 of the quality gate.

Pure functions, no I/O. This module decides which cost variant is allowed to
ship, so a bug here would silently ratify a degraded variant: it is the one
part of the harness that is unit-tested.

A task declares:
    facts:     [{id, on?, required, match}]   `on` = turn index; absent = any turn
    forbidden: [{id, on?, match, unless?}]    `unless` = an acceptable hedge

`match` and `unless` use bench.py's existing convention: `/regex/` (case
insensitive) or a plain case-insensitive substring.
"""
import re


def match_rule(pattern, text):
    """True if `pattern` matches `text`. `/regex/` or case-insensitive substring."""
    if not pattern:
        return False
    text = text or ""
    if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 1:
        return bool(re.search(pattern[1:-1], text, re.I))
    return pattern.lower() in text.lower()


def _answer_for(answers, idx):
    """The answer a rule applies to: one turn when `on` is set, else all of them."""
    answers = answers or []
    if idx is None:
        return "\n".join(answers)
    return answers[idx] if 0 <= idx < len(answers) else ""


def score_facts(facts, answers):
    found, missing, optional_found = [], [], []
    required = 0
    for f in facts or []:
        hit = match_rule(f.get("match"), _answer_for(answers, f.get("on")))
        if f.get("required"):
            required += 1
            (found if hit else missing).append(f.get("id"))
        elif hit:
            optional_found.append(f.get("id"))
    return {"found": found, "missing": missing,
            "required": required, "optional_found": optional_found}


def check_forbidden(forbidden, answers):
    """Ids of violated rules. A match that carries its `unless` hedge is NOT a
    violation — the baseline names an unconfirmed part reference while saying so,
    and that is correct behaviour, not a defect."""
    hits = []
    for f in forbidden or []:
        text = _answer_for(answers, f.get("on"))
        if not match_rule(f.get("match"), text):
            continue
        if f.get("unless") and match_rule(f["unless"], text):
            continue
        hits.append(f.get("id"))
    return hits


def quality_gate(task, answers):
    """Layer-1 verdict. `quality_gate` is None when the task declares no rules."""
    facts = score_facts(task.get("facts"), answers)
    hits = check_forbidden(task.get("forbidden"), answers)
    declared = bool(task.get("facts")) or bool(task.get("forbidden"))
    passed = (not facts["missing"] and not hits) if declared else None
    return {"facts": facts, "forbidden_hits": hits, "quality_gate": passed}
