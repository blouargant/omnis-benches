# omnis fixed prompt — measurement and reduction (2026-11-07)

Tools: [`prompt-size/`](../prompt-size) (fixed prompt of every agent, fake model
server, no model cost) and [`squad-bench/setup-ab.sh`](../squad-bench/setup-ab.sh)
(two omnis builds on the same config, whole fleet forced onto one model).

## Fixed prompt (first request of each agent, tokens ≈ chars/4)

| | before (`ef191f7`) | after | |
|---|---|---|---|
| System (leader) | 14,039 | 9,056 | −35 % |
| Kubernetes | 14,738 | 10,962 | −26 % |
| Knowledge | 14,114 | 10,337 | −27 % |
| Coding | 12,551 | 9,439 | −25 % |
| Helper | 12,835 | 10,216 | −20 % |
| Omnis router | 5,894 | 4,619 | −22 % |
| sum over 27 agents | 185,480 | 139,258 | −25 % |

Where it came from: the skill discipline stated five times, two stacked
"operating methods", narrated behaviour blocks (language, choice, steering,
out-of-scope, sub-agents), tool descriptions repeating their schema, the router
receiving the user-facing contract, the Helper receiving two loader protocols its
own instruction already covers. Rules from observed failures were kept.

## Behaviour A/B (squad-bench, `tasks-prompt-ab.json`, 9 tasks × 2, deepseek-v4.1-flash for every agent)

* **Correctness identical**: coding 4 tasks 8/8 both; web lookups same answers
  (2 ans, 2 738 mm); router routed to Knowledge and answered Canberra 2/2 both;
  System count 2/2 both. `helper-docs` is wrong in BOTH arms: the Helper says no
  global "one model for the fleet" setting exists — the single-model override is
  not documented in `web/docs`, so it cannot find it (docs gap, not a regression).
  (The first scoring showed 0/2 on three tasks: an `expect` written `/…/i`, which
  bench.py does not parse. Fixed and rescored from the recorded answers.)
* **Root prompt per call** (live): coder 11.6k → 8.7k, leader 10.3k → 6.3k,
  knowledge_leader 12.2k → 10.0k, router 5.1k → 4.1k.
* **Total cost unchanged in this sample** ($1.27 vs $1.29): sub-agents doing web
  fetches dominate (1.5M vs 1.95M tokens) and vary 2-3× between samples of the
  same task. Sub-agent calls 106 → 120: within that noise at n=2, worth a larger
  sample before claiming a total-cost saving.
* `ask_user` 0 in both; before, the Helper once called AskUserQuestion in a
  one-shot bench, after it ended with a prose offer.
