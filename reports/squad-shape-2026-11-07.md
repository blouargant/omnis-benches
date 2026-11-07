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
