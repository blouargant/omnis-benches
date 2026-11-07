# Squad shape under production tiering (2026-11-07)

Design: `omnis/docs/superpowers/specs/2026-11-07-squad-shape-design.md`;
plan: `omnis/docs/superpowers/plans/2026-11-07-squad-shape.md`.
Budget 50 € (58 $ at 1 € = 1.16 $); spend in `squad-shape-ledger.jsonl`.

## Gateway check

`claude-sonnet-5-5` (premium), no `max_tokens`, 1,500-word essay: `finish_reason:
stop` at **5,128** completion tokens — the 4,096 cap reported on 2026-10-31 is
gone; no `max_output_tokens` override needed.

## Arms (squad-bench/shapes.json) and their fixed prompt

Overlays built by `squad-bench/shape_overlay.py` and checked on the rendered
request with `prompt-size/` (no model cost): in every arm the squad root
declares no tool for a removed member and its instruction opens with the
"not available" note; Knowledge C declares `WebSearch` and `WebFetch`.

| Arm | Removed | Root fixed prompt (tokens) |
|---|---|---|
| coding-A | — | 9,051 |
| coding-B | reviewer | 8,801 |
| coding-C | reviewer, code_scout | 8,460 |
| knowledge-A | — | 9,949 |
| knowledge-B | research_critic | 9,597 |
| knowledge-C | research_critic, web_agent (+ web tools on the leader) | 9,693 |
| k8s-A | — | 10,651 |
| k8s-B | k8s_auditor | 10,146 |

## Coding — Terminal-Bench 2.1 smoke, 3 tasks × 2 attempts, production tiers

`TIERED=1 SHAPE=<arm> ./harbor/run.sh tb full smoke` (coder on `premium` =
Claude Sonnet 5.5; jobs `harbor/jobs/shape-tb-coding-*`).

| Arm | Resolved | Cost | configure-git | portfolio | rstan |
|---|---|---|---|---|---|
| A shipped | 4/6 | $0.596 | 1/2 | 1/2 | 2/2 |
| B no reviewer | 5/6 | $0.656 | 1/2 | 2/2 | 2/2 |
| C no reviewer, no scout | 5/6 | $0.687 | 1/2 | 2/2 | 2/2 |

**The coder called no sub-agent in any of the 18 trials** (every trial's usage
shows `coder` only). The arms therefore differ only by the ~250–600 tokens of
team description in the coder's prompt, and the gaps above are noise. Under the
adoption rule no arm costs less: **the Coding shape stays as shipped, undecided** —
this smoke does not exercise the members. A bench where a premium coder actually
delegates (larger codebases, DeepSWE) is needed to decide, and DeepSWE with
`premium` costs more than this whole budget.

## Knowledge — the 4 model-cost questions, production tiers, 2 blind judges

`MODEL=tiered OVERLAY=<arm> squad-bench/setup-ab.sh` + `run-shape-arm.sh`
(`web_fetcher` on `balanced` in every arm, as in the model-cost bench); judges
`claude-opus-5-5` and `gpt-5.5` (`judge_modelcost.py`). Data:
`squad-shape-knowledge/`.

| Arm | Cost | Wall | Judges (mean overall) | answers capped ≤ 5 |
|---|---|---|---|---|
| A shipped | $5.43 | 24 min | 6.88 | 2 |
| B no research_critic | $3.31 (−39 %) | 15 min | 6.50 | 2 |
| C leader alone with the web tools | $1.77 (−67 %) | 6 min | 7.00 | 1 |

Per question (cost $, A / B / C): LMCache 2.42 / 1.67 / 0.66, NetBird
0.45 / 0.33 / 0.16, Arkane 1.86 / 0.98 / 0.72, KServe 0.69 / 0.33 / 0.23.
The reference used 49 `web_agent` and 3 `research_critic` calls.

**C qualifies and is the cheapest → adopt.** Judges' notes on C: "most
actionable" (LMCache, both judges), "best balance" (NetBird, GPT); defects: one
answer in French to an English question (KServe), internal process chatter left
in two answers (all arms have this). One sample per question: C is "not visibly
worse and much cheaper", not "better".

Why the gatherer doctrine did not hold here: the leader on Sonnet 5.5 reads its
cache at $0.21/M, so holding fetched pages costs little, and alone it dosed the
research (one pass) where the squad fanned out 20 `web_agent` calls on LMCache.

## Kubernetes — k8s-ai-bench gatekeeper suite (31 tasks), production tiers

`OMNIS_SERVER_BIN` + `OMNIS_SYSTEM_CONFIG_DIR` from the same omnis build, arm B
with `OMNIS_BENCH_OVERLAY` (batches of 8, early-stop checked after each).

| Arm | Pass@1 | Cost |
|---|---|---|
| A shipped (two-pass audit: k8s_investigator then k8s_auditor) | 26/31 | $2.59 |
| B without k8s_auditor | 26/31 | $0.98 (−62 %) |

**Same tasks pass and fail in both arms** (failures: container-limits-ignore-cpu,
disallow-anonymous, disallowed-tags, pod-disruption-budget, required-probes).
In A the auditor ran on 21 of 31 tasks and roughly tripled their cost
(e.g. must-have-owner $0.152 vs $0.025) without turning a failure into a pass.
**B qualifies → adopt.** (The two-pass audit was added when the gatekeeper suite
was at 77 %; with today's k8s-audit skill and models the second pass adds nothing
here.)
