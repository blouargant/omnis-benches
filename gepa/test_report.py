import json

from gepa_omnis import report as R


def omnis(tmp_path):
    a = tmp_path / "omnis" / "registry" / "agents" / "leader"
    a.mkdir(parents=True)
    (a / "instruction.md").write_text("Old instruction.\n")
    (a / "agent.json").write_text(json.dumps({"name": "leader", "turn_reminder": "old"}, indent=2) + "\n")
    return tmp_path / "omnis"


SEEDS = {"instruction:leader": "Old instruction.\n", "turn_reminder:leader": "old"}
BEST = {"instruction:leader": "New instruction.\n", "turn_reminder:leader": "new"}


def test_patch_targets_omnis_paths(tmp_path):
    p = R.patch(omnis(tmp_path), SEEDS, BEST)
    assert "a/registry/agents/leader/instruction.md" in p
    assert "+New instruction." in p
    assert "a/registry/agents/leader/agent.json" in p and '+  "turn_reminder": "new"' in p
    assert R.patch(omnis(tmp_path / "x"), SEEDS, SEEDS) == ""


def test_report_contains_verdict_and_diff(tmp_path):
    decision = {"adopt": True, "rows": [{"agent": "leader", "model": "balanced", "base_mean": 0.5,
                                         "base_lo": 0.4, "base_hi": 0.6, "cand_mean": 0.8,
                                         "verdict": "better"}]}
    path = R.write(tmp_path / "reports", "leader-system", "2026-11-23",
                   config={"components": list(SEEDS), "models": ["balanced"]},
                   seeds=SEEDS, best=BEST, frontier=[(0, 0.4), (3, 0.7)],
                   decision=decision, spend={"eval": 12.5, "reflection": 1.25},
                   patch_text="--- a/x\n+++ b/x\n")
    text = path.read_text()
    assert path.name == "gepa-leader-system-2026-11-23.md"
    assert "Adopt: **yes**" in text and "| leader | balanced |" in text and "better" in text
    assert "+New instruction." in text and "$13.75" in text


def test_patch_applies_with_git_for_two_components(tmp_path):
    import subprocess
    src = omnis(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    best = {"instruction:leader": "New instruction.", "turn_reminder:leader": "new"}   # no final newline
    p = R.patch(src, SEEDS, best)
    (tmp_path / "p.diff").write_text(p)
    r = subprocess.run(["git", "apply", "--check", str(tmp_path / "p.diff")], cwd=src,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_patch_skips_prompt_components(tmp_path):
    from gepa_omnis import report as R
    assert R.patch(tmp_path, {"prompt:block.choice": "a"}, {"prompt:block.choice": "b"}) == ""
