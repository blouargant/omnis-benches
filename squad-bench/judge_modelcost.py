#!/usr/bin/env python3
"""Blind comparative LLM judge for the model-cost campaign.

For each task, every variant's final answer is shown to a judge model under a
random letter (order reshuffled per judge), and the judge scores each one on a
fixed rubric. Two judges from different model families are used so that no
variant is graded only by its own family.

Usage: judge_modelcost.py <dir-with-V*.jsonl> [--judges m1,m2] [--out file]
Needs OPENAI_BASE_URL / OPENAI_API_KEY (LiteLLM gateway).
"""
import argparse, glob, json, os, random, re, string, urllib.request

RUBRIC = """You are an expert technical reviewer grading research answers written by AI assistants.
All answers respond to the SAME user question. They are anonymised under letters, in random order.
Grade each answer independently on a 0-10 scale for:
- accuracy: are the technical claims correct and non-hallucinated? Cross-check the answers against each other and your own knowledge; penalise confident claims that look invented (fake versions, fake bug numbers, fake prices).
- completeness: does it cover every part of the question?
- evidence: are claims backed by concrete sources/links/version numbers the user could verify?
- usefulness: does it help the user take a decision (clear recommendation, trade-offs, next steps), without padding?
Then give an overall 0-10 (not a mechanical average: an answer with a serious factual error cannot score above 5).
Length is NOT quality: a concise complete answer beats a long padded one.
Reply with JSON only: {"scores": {"<letter>": {"accuracy":n,"completeness":n,"evidence":n,"usefulness":n,"overall":n,"note":"<=25 words"}}, "ranking": ["<best letter>", ...]}"""


def call(model, prompt):
    base = os.environ["OPENAI_BASE_URL"].rstrip("/")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 16000}
    req = urllib.request.Request(base + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"], d.get("usage", {})


def parse(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--judges", default="claude-opus-5-5,gpt-5.5")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    runs = {}  # task -> variant -> record
    for f in sorted(glob.glob(os.path.join(a.dir, "V*.jsonl"))):
        v = os.path.basename(f).split(".")[0]
        for line in open(f):
            r = json.loads(line)
            runs.setdefault(r["task"], {})[v] = r
    out = []
    for task, byv in sorted(runs.items()):
        q = next(iter(byv.values()))["prompts"][0]
        for ji, judge in enumerate(a.judges.split(",")):
            vs = [v for v in byv if (byv[v].get("answer") or "").strip()]
            rnd = random.Random(f"{task}-{judge}")
            rnd.shuffle(vs)
            letters = dict(zip(string.ascii_uppercase, vs))
            parts = [RUBRIC, "\n\n=== USER QUESTION ===\n" + q]
            for L, v in letters.items():
                parts.append(f"\n\n=== ANSWER {L} ===\n" + byv[v]["answer"])
            txt, usage = call(judge, "".join(parts))
            try:
                res = parse(txt)
            except Exception as e:
                print("parse failure", task, judge, e, txt[:300]); continue
            for L, s in res["scores"].items():
                if L in letters:
                    out.append({"task": task, "judge": judge, "variant": letters[L], **s})
            print(task, judge, "ranking:", [letters.get(L, L) for L in res.get("ranking", [])], usage.get("prompt_tokens"))
    if a.out:
        with open(a.out, "w") as fh:
            for r in out:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
