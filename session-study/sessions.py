"""Read omnis conversation files: sessions, turns, tool calls, call outline."""
import glob
import json
import os
import re

_VALUE = re.compile(r':\s*"((?:[^"\\]|\\.)*)')


def load(logs_dir):
    """Sessions of logs_dir as {"id","squad","skills","turns"} plus a summary of
    what was skipped. Hidden sessions are not read past their flag."""
    out, summary = [], {"files": 0, "hidden": 0, "legacy": 0, "unreadable": 0}
    for path in sorted(glob.glob(os.path.join(logs_dir, "conversation_*.json"))):
        summary["files"] += 1
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            summary["unreadable"] += 1
            continue
        if not isinstance(doc, dict):
            summary["legacy"] += 1
            continue
        if doc.get("hidden"):
            summary["hidden"] += 1
            continue
        turns = doc.get("turns")
        skills = doc.get("skills")
        out.append({
            "id": os.path.basename(path)[len("conversation_"):-len(".json")],
            "squad": doc.get("squad") or "",
            "skills": [{"name": s.get("name", ""), "turn": s.get("turn", 0)}
                       for s in skills if isinstance(s, dict)] if isinstance(skills, list) else [],
            "turns": [t for t in turns if isinstance(t, dict)] if isinstance(turns, list) else [],
        })
    return out, summary


def walk(calls, depth=0):
    """Each call with its depth, a sub-agent's own calls after their parent."""
    for call in calls or []:
        if not isinstance(call, dict):
            continue
        yield call, depth
        yield from walk(call.get("children"), depth + 1)


def text_of(raw):
    """The text of an args/result value whatever its shape."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, ensure_ascii=False, sort_keys=True)


def strings_of(raw):
    """The string values a result carries: a dict's top-level strings, the
    values still readable in JSON that was cut, or the bare string."""
    if isinstance(raw, dict):
        return [v for v in raw.values() if isinstance(v, str)]
    if not isinstance(raw, str):
        return []
    if raw.lstrip().startswith("{"):
        try:
            return strings_of(json.loads(raw))
        except ValueError:
            return [m.replace('\\"', '"').replace("\\n", "\n") for m in _VALUE.findall(raw)]
    return [raw]


def _cut(text, n):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "…"


def outline(turn, cut=300):
    """One line per call: "<indent><agent>.<name>(<args>) -> <result>"."""
    lines = []
    for call, depth in walk(turn.get("tools")):
        who = (call.get("agent") or "") + "." if call.get("agent") else ""
        lines.append("%s%s%s(%s) -> %s" % ("  " * depth, who, call.get("name", "?"),
                                          _cut(text_of(call.get("args")), cut),
                                          _cut(text_of(call.get("result")), cut)))
    return "\n".join(lines)
