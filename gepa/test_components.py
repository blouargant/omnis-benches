import json

import pytest

from gepa_omnis import components as C


def make_omnis(tmp_path):
    src = tmp_path / "omnis"
    a = src / "registry" / "agents"
    (a / "leader").mkdir(parents=True)
    (a / "leader" / "agent.json").write_text(json.dumps(
        {"name": "leader", "tools": ["Bash", "Skill"], "skills": ["review"],
         "turn_reminder": "[Delegate.]"}))
    (a / "leader" / "instruction.md").write_text("You coordinate.\n")
    (a / "coder").mkdir()
    (a / "coder" / "agent.json").write_text(json.dumps({"name": "coder", "tools": ["Skill"]}))
    (a / "scout").mkdir()
    (a / "scout" / "agent.json").write_text(json.dumps({"name": "scout", "tools": ["Read"]}))
    s = src / "registry" / "skills" / "review"
    s.mkdir(parents=True)
    (s / "SKILL.md").write_text("---\nname: review\ndescription: Review.\n---\n# Review\nBody.\n")
    return src


def make_base(tmp_path):
    base = tmp_path / "base"
    (base / "registry" / "agents" / "leader").mkdir(parents=True)
    (base / "registry" / "agents" / "leader" / "agent.json").write_text(
        json.dumps({"model_ref": "balanced"}))
    (base / "models.json").write_text("{}")
    return base


def test_parse_rejects_unknown_kind():
    assert C.parse("instruction:leader") == ("instruction", "leader")
    with pytest.raises(ValueError):
        C.parse("tool:Bash")
    with pytest.raises(ValueError):
        C.parse("instruction")


def test_seed_reads_instruction_and_reminder(tmp_path):
    src = make_omnis(tmp_path)
    seed = C.read_seed(src, ["instruction:leader", "turn_reminder:leader", "skill:review"])
    assert seed["instruction:leader"] == "You coordinate.\n"
    assert seed["turn_reminder:leader"] == "[Delegate.]"
    assert seed["skill:review"] == "# Review\nBody.\n"


def test_prompt_component_not_implemented(tmp_path):
    with pytest.raises(NotImplementedError):
        C.read_seed(make_omnis(tmp_path), ["prompt:contract.root"])


def test_apply_merges_reminder_keeps_model_ref(tmp_path):
    home = tmp_path / "home"
    C.apply_candidate(home, make_base(tmp_path), {"turn_reminder:leader": "NEW"})
    aj = json.loads((home / "registry/agents/leader/agent.json").read_text())
    assert aj == {"model_ref": "balanced", "turn_reminder": "NEW"}


def test_apply_skill_keeps_front_matter(tmp_path):
    src = make_omnis(tmp_path)
    home = tmp_path / "home"
    C.apply_candidate(home, make_base(tmp_path), {"skill:review": "# New\n"}, omnis_src=src)
    text = (home / "registry/skills/review/SKILL.md").read_text()
    assert text == "---\nname: review\ndescription: Review.\n---\n# New\n"


def test_apply_resets_previous_candidate(tmp_path):
    home, base = tmp_path / "home", make_base(tmp_path)
    C.apply_candidate(home, base, {"instruction:leader": "A"})
    assert (home / "registry/agents/leader/instruction.md").read_text() == "A"
    C.apply_candidate(home, base, {"turn_reminder:leader": "B"})
    assert not (home / "registry/agents/leader/instruction.md").exists()


def test_roundtrip_utf8(tmp_path):
    home = tmp_path / "home"
    text = "Délègue — « vite »\n"
    C.apply_candidate(home, make_base(tmp_path), {"instruction:leader": text})
    assert (home / "registry/agents/leader/instruction.md").read_bytes() == text.encode("utf-8")


def test_reach_skill_empty_list_means_all(tmp_path):
    src = make_omnis(tmp_path)
    assert C.agents_reached("skill:review", src) == {"leader", "coder"}
    assert C.agents_reached("instruction:scout", src) == {"scout"}
