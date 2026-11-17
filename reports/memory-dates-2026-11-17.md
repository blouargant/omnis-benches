# Collection memory: dates and confirmations (2026-11-17)

## What was tested

omnis `develop` (105f46c) plus the uncommitted dates change:

- Each memory carries `created`, `updated`, and, when the user restated it, `confirmations` and `last_confirmed`.
- `memory_save` takes `confirms=true` when the user restates what a memory already says. That adds one confirmation. A change resets the count.
- The block shows `(saved D, updated D, restated N× (last D))` for each memory and ends with `Today is <date>.`
- The rules say:
  - when two memories disagree, the most recent wins;
  - rules and facts about the user do not expire;
  - a project fact or reference that is months old is given with its date and flagged as possibly outdated.
- When the block is over budget, the least restated and least recent memories are shortened first.

Harness changes:

- `memory_bench.py` gains a `restate` scenario: remember a rule, restate it in another chat, then use it. It checks that there is one memory with ≥ 1 confirmation.
- `update` now also checks that a changed fact is not counted as a confirmation (`no_false_confirm`).
- Each step record now keeps the question the model asked the user (`ask_detail`).

Runs: `memory_bench.py` ×3 and `memory_quality.py` (orders-api + newsletter) ×3 per tier, judged by Fable 5.2. Raw records: `memory-dates-2026-11-17.jsonl` and `memory-dates-2026-11-17-recall.jsonl`, which also holds the correction re-runs (`before-balanced`, `d`). Baseline: `memory-narrow-2026-11-10.md`.

## Result

memory_bench:

| Tier | restate | update | forget | correction | Other |
|---|---|---|---|---|---|
| high | 3/3 | 3/3 | 2/3 | 3/3 | explicit 3/3, no-pollution 3/3 |
| balanced | 3/3 | 3/3 | 3/3 | 0/3 | explicit 3/3, no-pollution 3/3 |

In every `restate` run, the restated rule ended as one memory with a confirmation, on both tiers. No `update` run counted a changed fact as a confirmation.

memory_quality, mean of 3:

| Tier | Conversation | Before (narrowed) | Dates | Recall | Applied | Cost |
|---|---|---|---|---|---|---|
| high | orders-api | 9.0 | 8.7 | 1.00 | 0.89 | $0.28 |
| high | newsletter | 8.7 | 8.3 | 1.00 | 0.83 | $0.16 |
| balanced | orders-api | 7.3 | **8.7** | 1.00 | 0.94 | $0.16 |
| balanced | newsletter | 6.7 | 6.3 | 0.92 | 0.42 | $0.08 |

Precision on high is 1.00 in all six conversations, and no forbidden item was saved on that tier. On balanced, one newsletter run scored 4/10 with one violation.

## Findings

1. **Confirmations work.** Both tiers call `memory_save(confirms=true)` when a rule is restated (6/6), instead of creating a duplicate. Neither marks a changed fact as a confirmation.
2. **No quality regression.** The high scores are within one point of the baseline, with recall and precision unchanged. Balanced orders-api rises to 8.7. Its earlier low run, a missed `stg2` correction, did not recur.
3. **The balanced `correction` failures are a permission card, not memory.** In those runs, balanced treats "write a commit message for this change" as a task in a repository. It runs `cd /home/user/repos/… && git diff`, and the shipped `cd /` ask rule raises a card the bench cannot answer.
   - The committed build without this change does the same: 2 of 4 runs.
   - In the runs that did not hit the card, the memory was saved and applied.
4. **The empty-cut retry from 105f46c fired 5 times on balanced**, and no reply cut at the output limit reached a result.

## Decision

Keep the change.

## Follow-up: the permission card was an omnis bug

The bench sets `defaultMode: bypassPermissions` in the user layer, so the `cd /` card should never have appeared. It did because `permissions.Merge` took the system layer's mode (`acceptEdits`, shipped since 2026-11-08) over every user-layer mode. Fixed in omnis (the highest layer that names a mode wins). Re-run of `correction` on balanced with the fix: **4/4** (label `modefix-balanced`).

Every bench run since `acceptEdits` shipped therefore ran in `acceptEdits` instead of `bypassPermissions`. Only commands hitting an explicit `ask` rule were affected: they surfaced as `ask_user` failures and were not silently mis-scored.

What remains is model behaviour, not memory: balanced sometimes treats "write a commit message for this change" as work in a repository and invents a path (`/home/user/repos/vibe-coding`).
