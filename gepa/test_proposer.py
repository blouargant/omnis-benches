import json

from gepa_omnis import proposer as P

SEEDS = {"instruction:leader": "Coordinate the squad and delegate evidence to the investigator.",
         "turn_reminder:leader": "Two questions = two calls."}
DATASET = {"instruction:leader": [{"Inputs": "q", "Generated Outputs": "a", "Feedback": "Run 1: FAILED"}]}


class Scripted:
    def __init__(self, *outs):
        self.outs, self.prompts = list(outs), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.outs.pop(0)


def make(reflection, keep_answer="YES", keep=None, tmp_path=None):
    return P.GuardedProposer(
        reflection=reflection, keep_check=lambda p: keep_answer, seeds=SEEDS,
        deny={"relay-07"}, keep=keep or {"instruction:leader": ["Delegate evidence."]},
        reach={k: {"leader"} for k in SEEDS}, log=tmp_path / "proposals.jsonl")


def test_proposer_accepts_clean_text(tmp_path):
    r = Scripted("```\nCoordinate; delegate evidence to the investigator first.\n```")
    out = make(r, tmp_path=tmp_path)(dict(SEEDS), DATASET, ["instruction:leader"])
    assert out == {"instruction:leader": "Coordinate; delegate evidence to the investigator first."}
    log = [json.loads(l) for l in (tmp_path / "proposals.jsonl").read_text().splitlines()]
    assert log[-1]["verdict"] == "accepted"


def test_proposer_retries_on_leak_then_accepts(tmp_path):
    r = Scripted("```\nAlways check relay-07 first.\n```", "```\nDelegate evidence early.\n```")
    out = make(r, tmp_path=tmp_path)(dict(SEEDS), DATASET, ["instruction:leader"])
    assert out["instruction:leader"] == "Delegate evidence early."
    assert "relay-07" in r.prompts[1]          # the retry names the rejection


def test_proposer_keeps_parent_after_three_rejections(tmp_path):
    r = Scripted(*["```\n" + "x" * 500 + "\n```"] * 3)
    out = make(r, tmp_path=tmp_path)(dict(SEEDS), DATASET, ["instruction:leader"])
    assert out["instruction:leader"] == SEEDS["instruction:leader"]
    assert len(r.prompts) == 3


def test_proposer_rejects_identical_and_unfenced(tmp_path):
    r = Scripted("Delegate more.", "```\n" + SEEDS["instruction:leader"] + "\n```", "```\n\n```")
    out = make(r, tmp_path=tmp_path)(dict(SEEDS), DATASET, ["instruction:leader"])
    assert out["instruction:leader"] == SEEDS["instruction:leader"]


def test_proposer_rejects_dropped_rule(tmp_path):
    r = Scripted(*["```\nDo whatever.\n```"] * 3)
    out = make(r, keep_answer="NO", tmp_path=tmp_path)(dict(SEEDS), DATASET, ["instruction:leader"])
    assert out["instruction:leader"] == SEEDS["instruction:leader"]


def test_template_has_gepa_placeholders():
    assert "<curr_param>" in P.REFLECTION_TEMPLATE and "<side_info>" in P.REFLECTION_TEMPLATE
    assert "niche and domain specific factual information" not in P.REFLECTION_TEMPLATE
