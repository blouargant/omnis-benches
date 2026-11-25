"""Cards a human reads to say whether a turn failed, and what that tells about
each way of flagging a turn."""
import json
import os
import random

VALID = ("yes", "no")
REPLY_END = 600
OUTLINE_CAP = 8000


def _why(turn, judged):
    by_signal = bool(turn.get("signals"))
    by_judge = (judged.get(turn["turn_id"]) or {}).get("verdict") in ("failed", "wasteful")
    return "both" if by_signal and by_judge else "signal" if by_signal else "judge" if by_judge else ""


def pick(turns, judged, controls=8, seed=20261125):
    """Every flagged turn, plus `controls` turns nobody flagged, in one shuffled
    list numbered after the shuffle."""
    rnd = random.Random(seed)
    cards, clean = [], []
    for t in turns:
        why = _why(t, judged)
        (cards if why else clean).append({"turn_id": t["turn_id"], "why": why or "control"})
    cards += rnd.sample(clean, min(controls, len(clean)))
    rnd.shuffle(cards)
    return [{"card": "c%02d" % (i + 1), "turn_id": c["turn_id"], "why": c["why"]} for i, c in enumerate(cards)]


def _ends(text, n):
    if len(text) <= 2 * n:
        return text
    return "%s\n\n[… %d characters not shown …]\n\n%s" % (text[:n], len(text) - 2 * n, text[-n:])


def _outline(text):
    if len(text) <= OUTLINE_CAP:
        return text
    lines = text.splitlines()
    head, tail, size, i, j = [], [], 0, 0, len(lines) - 1
    while i < j and size + len(lines[i]) + len(lines[j]) < OUTLINE_CAP:
        head.append(lines[i])
        tail.append(lines[j])
        size += len(lines[i]) + len(lines[j])
        i, j = i + 1, j - 1
    return "\n".join(head + ["[… %d calls not shown …]" % (j - i + 1)] + tail[::-1])


def card_markdown(card_id, turn):
    """What the reader needs to judge the turn — and nothing saying why it was picked."""
    return "\n".join([
        "## %s" % card_id, "",
        "**Request**", "", turn.get("user_text", "") or "(empty)", "",
        "**Tool calls** (%d)" % len((turn.get("outline") or "").splitlines()), "",
        "```", _outline(turn.get("outline", "")) or "(none)", "```", "",
        "**Reply**", "", _ends(turn.get("reply", ""), REPLY_END) or "(empty)", "",
        "**Next user message**", "", turn.get("next_user_text", "") or "(none)", "",
    ])


def read_verdicts(path):
    """Valid yes/no answers, and the cards still open (blank, unsure, anything else)."""
    if not os.path.exists(path):
        return {}, []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    valid, open_ = {}, []
    for card, v in sorted(raw.items()):
        answer = str(v.get("failure", "")).strip().lower() if isinstance(v, dict) else ""
        if answer in VALID:
            valid[card] = {"failure": answer, "kind": str(v.get("kind") or ""), "note": str(v.get("note") or "")}
        else:
            open_.append(card)
    return valid, open_


def _row(flagged_cards, flagged_total, verdicts):
    checked = [c for c in flagged_cards if c["card"] in verdicts]
    real = sum(1 for c in checked if verdicts[c["card"]]["failure"] == "yes")
    return {"flagged": flagged_total, "checked": len(checked), "real": real,
            "precision": real / len(checked) if checked else None}


def precision(cards, verdicts, turns, judged):
    """Per signal and for the judge: how many flagged turns the reader confirmed."""
    cards = [c for c in cards if c["turn_id"] in turns]  # a session deleted since the cards were picked
    rows = {}
    names = sorted({s for t in turns.values() for s in t.get("signals", [])})
    for name in names:
        has = lambda tid: name in turns[tid].get("signals", [])
        rows[name] = _row([c for c in cards if has(c["turn_id"])], sum(1 for tid in turns if has(tid)), verdicts)
    by_judge = lambda tid: (judged.get(tid) or {}).get("verdict") in ("failed", "wasteful")
    rows["judge"] = _row([c for c in cards if by_judge(c["turn_id"])], sum(1 for tid in turns if by_judge(tid)), verdicts)
    ctl = [c for c in cards if c["why"] == "control" and c["card"] in verdicts]
    return {"rows": rows, "controls_checked": len(ctl),
            "controls_real": sum(1 for c in ctl if verdicts[c["card"]]["failure"] == "yes")}
