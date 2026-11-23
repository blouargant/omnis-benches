"""Checks a proposed text must pass before GEPA may evaluate it."""
import re
from pathlib import Path

KEEP_DIR = Path(__file__).resolve().parent.parent / "keep"
_STRIP = "\"'`.,;:!?()[]{}<>«»"


def _scripted_texts(task):
    texts = [task.get("prompt", "")] + list(task.get("prompts") or [])
    for rules in (task.get("fake") or {}).values():
        texts += [r.get("reply", "") for r in rules if isinstance(r, dict)]
    return texts


def _name_like(tok):
    return len(tok) >= 4 and (any(c.isdigit() for c in tok) or any(c in tok for c in "/_."))


def denylist(items, seeds):
    """Scenario names a proposal must not contain: tokens of the prompts and
    scripted replies that look like names (digit, '/', '_', '.') and words in
    backticks, minus anything the seed texts already say. Fact-pattern words are
    left out: they are mostly ordinary words ("cannot", "memory") whose ban would
    reject sound proposals."""
    deny = set()
    for it in items:
        for text in _scripted_texts(it.task):
            deny |= {w.strip().lower() for w in re.findall(r"`([^`]+)`", text) if len(w.strip()) >= 4}
            for tok in text.split():
                tok = tok.strip(_STRIP)
                if _name_like(tok):
                    deny.add(tok.lower())
    seed_text = "\n".join(seeds)
    return {w for w in deny if not leaks(seed_text, {w})}


def leaks(text, deny):
    found = []
    for w in sorted(deny):
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", text, re.I):
            found.append(w)
    return found


def too_long(text, seed, ratio=1.30):
    return len(text) > ratio * max(len(seed), 1)


def load_keep(name):
    kind, _, target = name.partition(":")
    path = KEEP_DIR / f"{kind}-{target}.txt"
    if not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


KEEP_PROMPT = """Does the text below still state this rule, possibly reworded? Answer YES or NO.

Rule: {rule}

Text:
<<<
{text}
>>>"""


def dropped_rules(candidate, rules, ask):
    text = "\n\n".join(candidate.values())
    return [r for r in rules
            if not ask(KEEP_PROMPT.format(rule=r, text=text)).strip().upper().startswith("YES")]
