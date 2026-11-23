"""Candidate components: the omnis texts GEPA may rewrite.

A component name is `<kind>:<target>`:
  instruction:<agent>    registry/agents/<agent>/instruction.md
  turn_reminder:<agent>  `turn_reminder` in registry/agents/<agent>/agent.json
  skill:<name>           body of registry/skills/<name>/SKILL.md (front matter kept)
  prompt:<id>            omnis prompt_overrides.json (needs omnis spec part 1)
"""
import json
import shutil
from pathlib import Path

KINDS = ("instruction", "turn_reminder", "skill", "prompt")
_NO_PROMPTS = "prompt components need omnis prompt_overrides (spec part 1)"


def parse(name):
    kind, sep, target = name.partition(":")
    if not sep or not target or kind not in KINDS:
        raise ValueError(f"bad component name {name!r} (want <kind>:<target>, kind in {KINDS})")
    return kind, target


def _agent_dir(src, agent):
    return Path(src) / "registry" / "agents" / agent


def _skill_file(src, skill):
    return Path(src) / "registry" / "skills" / skill / "SKILL.md"


def split_front_matter(text):
    """Return (front_matter_with_delimiters, body)."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[:end + 5], text[end + 5:]
    return "", text


def read_seed(omnis_src, names):
    seed = {}
    for name in names:
        kind, target = parse(name)
        if kind == "instruction":
            seed[name] = (_agent_dir(omnis_src, target) / "instruction.md").read_text(encoding="utf-8")
        elif kind == "turn_reminder":
            aj = json.loads((_agent_dir(omnis_src, target) / "agent.json").read_text(encoding="utf-8"))
            seed[name] = aj.get("turn_reminder", "")
        elif kind == "skill":
            seed[name] = split_front_matter(_skill_file(omnis_src, target).read_text(encoding="utf-8"))[1]
        else:
            raise NotImplementedError(_NO_PROMPTS)
    return seed


def apply_candidate(home, base_overlay, candidate, omnis_src=None):
    """Reset the overlay part of `home` to `base_overlay`, then write `candidate`."""
    home, base = Path(home), Path(base_overlay)
    shutil.rmtree(home / "registry", ignore_errors=True)
    home.mkdir(parents=True, exist_ok=True)
    if (base / "registry").is_dir():
        shutil.copytree(base / "registry", home / "registry")
    if (base / "models.json").is_file():
        shutil.copy2(base / "models.json", home / "models.json")
    for name, text in candidate.items():
        kind, target = parse(name)
        if kind == "instruction":
            p = _agent_dir(home, target) / "instruction.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        elif kind == "turn_reminder":
            p = _agent_dir(home, target) / "agent.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            aj = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
            aj["turn_reminder"] = text
            p.write_text(json.dumps(aj, indent=1, ensure_ascii=False), encoding="utf-8")
        elif kind == "skill":
            if omnis_src is None:
                raise ValueError("skill components need omnis_src for the front matter")
            front, _ = split_front_matter(_skill_file(omnis_src, target).read_text(encoding="utf-8"))
            p = _skill_file(home, target)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(front + text, encoding="utf-8")
        else:
            raise NotImplementedError(_NO_PROMPTS)


def agents_reached(name, omnis_src):
    kind, target = parse(name)
    if kind in ("instruction", "turn_reminder"):
        return {target}
    if kind == "prompt":
        raise NotImplementedError(_NO_PROMPTS)
    out = set()
    for aj in sorted((Path(omnis_src) / "registry" / "agents").glob("*/agent.json")):
        a = json.loads(aj.read_text(encoding="utf-8"))
        skills = a.get("skills") or []
        if target in skills or ("Skill" in (a.get("tools") or []) and not skills):
            out.add(aj.parent.name)
    return out
