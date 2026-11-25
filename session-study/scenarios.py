"""Turn a confirmed failure into a bench scenario, and check that nothing of
the session it came from is left in it."""
import json
import re

import llm

# Names a scenario may share with its source: common technology and calendar
# words. Anything else needs --allow, decided by the person reading the draft.
ALLOWED = set("""
api aws azure claude cpu css debian docker gcp github gitlab go google gpu html http https
huggingface intel java javascript json kubernetes linux llm macos markdown mysql nvidia openai
pdf postgresql python redis rust sql ssh typescript ubuntu url windows yaml
monday tuesday wednesday thursday friday saturday sunday january february march april may june
july august september october november december
""".split())

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PATH = re.compile(r"(?<![\w:/.])~?/(?:[\w.\-]+/)*[\w.\-]+")
_HOST = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.I)
_NUMBER = re.compile(r"\b\d{4,}\b")
_NAME = re.compile(r"\b[A-ZÀ-Þ]\w+")
_SENTENCE_START = re.compile(r"(?:^|[.!?:;\n]\s*|^\s*[-*•]\s*)$")


def _tokens(source):
    """What must not survive in a scenario: e-mails, paths, hosts, long numbers, names."""
    found, text = set(), source

    def take(rx, keep=lambda s: True):
        nonlocal text
        for m in rx.finditer(text):
            tok = m.group(0).rstrip(".")
            if keep(tok):
                found.add(tok)
        text = rx.sub(lambda m: " " * len(m.group(0)), text)

    take(_EMAIL)
    take(_PATH, lambda s: len(s) > 2 and re.search(r"[A-Za-z]", s))
    take(_HOST)
    for m in _NUMBER.finditer(text):
        if not (len(m.group(0)) == 4 and 1900 <= int(m.group(0)) <= 2099):
            found.add(m.group(0))
    for m in _NAME.finditer(text):
        if not _SENTENCE_START.search(text[:m.start()][-4:]) and m.start() != 0:
            found.add(m.group(0))
    return found


def _draft_text(draft):
    parts = [draft.get("prompt") or ""] + list(draft.get("prompts") or [])
    rubric = draft.get("rubric") or {}
    parts += list(rubric.get("pass") or []) + [rubric.get("failure") or ""]
    for name, content in (draft.get("files") or {}).items():
        parts += [name, content if isinstance(content, str) else json.dumps(content)]
    return "\n".join(str(p) for p in parts)


def leaks(source_text, draft, allowed=()):
    """Tokens of the source still present in the draft, sorted."""
    ok = ALLOWED | {a.lower() for a in allowed}
    text = _draft_text(draft)
    out = []
    for tok in _tokens(source_text or ""):
        if tok.lower() in ok:
            continue
        if re.search(r"(?<![\w])%s(?![\w])" % re.escape(tok), text, re.I):
            out.append(tok)
    return sorted(out)


def source_text(turn):
    return "\n".join([turn.get("user_text", ""), turn.get("reply", ""), turn.get("outline", ""),
                      turn.get("next_user_text", "")] + list(turn.get("earlier_user_texts") or []))


DRAFT_SYSTEM = """You write one test scenario for an AI agent from a recorded turn of a real session.
The scenario asks for the SAME kind of task, rewritten: replace every person, company, project, path, host name and figure of the session by an invented one of the same kind. Keep the names of public products or technologies only when the task is about them. Keep the language of the request.
- "prompts": the user messages to send, in order. One message when the request stands alone; the earlier messages too when the failure needs them.
- "kind": "web" when answering needs the web, else "".
- "rubric.pass": 2 to 5 statements a reviewer can check on an answer.
- "rubric.failure": one sentence naming the specific failure seen in the session, observable in an answer or in run metrics (tool calls, delegations, pages fetched, cost, time). Empty for a control scenario.
- "files": {"<name>": "<content>"} only when the turn read local files; invent the content.
""" + llm.FENCE_RULE + """
Reply with JSON only: {"prompts": [...], "kind": "...", "rubric": {"pass": [...], "failure": "..."}, "files": {...}}"""


def draft_prompt(turn, earlier_user_texts, failure_kind, note, control):
    if control:
        head = "CONTROL SCENARIO: this turn went well. rubric.failure must be empty."
    else:
        head = "What went wrong, as the reviewer put it: %s\nReviewer's note: %s" % (
            failure_kind or "(not named)", note or "(none)")
    body = "EARLIER USER MESSAGES\n%s\n\nREQUEST\n%s\n\nTOOL CALLS\n%s\n\nREPLY\n%s" % (
        "\n---\n".join(earlier_user_texts) or "(none)", turn.get("user_text", ""),
        (turn.get("outline", "") or "(none)")[:20000], (turn.get("reply", "") or "(empty)")[:6000])
    return DRAFT_SYSTEM, head + "\n\n" + llm.fence(body)


def parse_draft(text, scenario_id, squad):
    d = llm.extract_json(text)
    prompts = [p.strip() for p in (d.get("prompts") or []) if isinstance(p, str) and p.strip()]
    rubric = d.get("rubric") if isinstance(d.get("rubric"), dict) else {}
    passes = [p for p in (rubric.get("pass") or []) if isinstance(p, str) and p.strip()]
    failure = str(rubric.get("failure") or "").strip()
    control = scenario_id.startswith("ss-c")
    if not prompts:
        raise ValueError("no request")
    if not passes:
        raise ValueError("rubric.pass is empty")
    if control and failure:
        raise ValueError("a control scenario must have an empty rubric.failure")
    if not control and not failure:
        raise ValueError("rubric.failure is empty")
    out = {"id": scenario_id, "squad": squad, "kind": str(d.get("kind") or "")}
    if len(prompts) == 1:
        out["prompt"] = prompts[0]
    else:
        out["prompts"] = prompts
    out["rubric"] = {"pass": passes, "failure": failure}
    files = d.get("files")
    if isinstance(files, dict) and files:
        out["files"] = {str(k): v if isinstance(v, str) else json.dumps(v) for k, v in files.items()}
    return out


def run_draft(cards, verdicts, turns, model, call=llm.call):
    """Scenarios for every card marked yes, then two controls from cards marked
    no (same squad as the failures first). Returns (drafts, sources, errors)."""
    yes = [c for c in cards if verdicts.get(c["card"], {}).get("failure") == "yes"]
    no = [c for c in cards if verdicts.get(c["card"], {}).get("failure") == "no"]
    squads = {turns[c["turn_id"]].get("squad") for c in yes}
    no.sort(key=lambda c: turns[c["turn_id"]].get("squad") not in squads)
    plan = [("ss-%d" % (i + 1), c) for i, c in enumerate(yes)]
    plan += [("ss-c%d" % (i + 1), c) for i, c in enumerate(no[:2])]
    drafts, sources, errors = [], {}, []
    for sid, card in plan:
        turn = turns[card["turn_id"]]
        v = verdicts[card["card"]]
        try:
            system, user = draft_prompt(turn, list(turn.get("earlier_user_texts") or []),
                                        v.get("kind", ""), v.get("note", ""), sid.startswith("ss-c"))
            text, _ = call(model, system, user)
            drafts.append(parse_draft(text, sid, turn.get("squad", "")))
            sources[sid] = card["turn_id"]
        except Exception as e:  # one bad draft must not lose the others
            errors.append("%s (card %s): %s: %s" % (sid, card["card"], type(e).__name__, e))
    return drafts, sources, errors


def accept(drafts, texts, ids, allowed=()):
    """The drafts named by ids, if none leaks. texts: scenario id -> source text."""
    by_id = {d["id"]: d for d in drafts}
    out = []
    for sid in ids:
        if sid not in by_id:
            raise ValueError("no draft named %s" % sid)
        found = leaks(texts.get(sid, ""), by_id[sid], allowed)
        if found:
            raise ValueError("%s still contains session text: %s" % (sid, ", ".join(found)))
        out.append(by_id[sid])
    return out
