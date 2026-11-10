# Collection memory: per-message reminder (2026-11-10)

## What was tested

omnis `develop` (e296675, provenance guard) plus two uncommitted changes:

- **Per-message reminder.** A short static note is appended as the last part of every typed user message in the model request. It says to call `memory_save` first when the message corrects or criticises a draft, states a preference, says who the user is or gives a lasting fact; one memory per rule; follow the memory and pitch the answer to the user's profile. It is put on every message so the request prefix stays stable for the prompt cache. It is skipped on the router, hidden sessions and unattended turns.
- **Rules (`collmem.Rules`).** Added three points:
  - feedback on a draft is a correction;
  - one memory per rule;
  - use what is remembered, including the user's profile.

Harness and setup:

- `memory_quality.py` (orders-api + newsletter) ×3, judged by Fable 5.2.
- `memory_bench.py` ×3.
- One server per tier (`setup-ab.sh`, `MODEL=ref:<tier>`).
- Raw records: `memory-remind-2026-11-10.jsonl` and `memory-remind-2026-11-10-recall.jsonl`.

Baselines:

- newsletter: `memory-quality-2026-11-10.md`, run before the guard. The guard does not affect this conversation.
- orders-api and memory_bench: `memory-guard-2026-11-10.md`.

## Result (mean of 3)

| Tier | Conversation | recall | applied | judge /10 |
|---|---|---|---|---|
| high, before | newsletter | 0.75 | 0.67 | 6.3 |
| high, reminder | newsletter | **1.00** | **0.83** | **7.7** |
| balanced, before | newsletter | 0.21 | 0.67 | 2.0 |
| balanced, reminder | newsletter | **0.83** | 0.58 | **5.7** |
| high, before | orders-api | 1.00 | 0.83 | 8.7 |
| high, reminder | orders-api | 1.00 | **0.94** | **9.0** |
| balanced, before | orders-api | 0.77 | 0.67 | 6.0 |
| balanced, reminder | orders-api | **0.93** | **0.89** | **8.0** |

memory_bench:

| Tier | Before | Reminder |
|---|---|---|
| high | 14/15 | **15/15** |
| balanced | 12/15 | **14/15** |

All three balanced `correction` runs now save. They failed 2/3 before, with `writes=0`. The one balanced fail is an `update` run (285 s, stale value kept). The no-pollution test passes 6/6: no memory is written on a plain question.

Cost:

| Tier | Conversation | Before | Reminder |
|---|---|---|---|
| high | orders-api | $0.77 | $0.79 |
| high | newsletter | — | $0.51 |
| balanced | orders-api | $0.88 | $0.79 |
| balanced | newsletter | — | $0.59 |

## Findings

1. **Draft feedback is now saved.** On newsletter, high stores every expected rule in all three runs (recall 1.00). Balanced goes from 0.21 to 0.83.
2. **The profile is used more.** "applied" rises on orders-api for both tiers: high 0.83 → 0.94, balanced 0.67 → 0.89.
3. **New over-saving on high.** In 2 of 3 newsletter runs high saved the one-off outing details (date, place, time) as a `project` memory. This is forbidden item F2, and it costs those runs their precision (0.86). The reminder's "lasting fact" is read too broadly. A next wording could exclude details of the current task explicitly, but that change has not been measured.
4. **Balanced misses remain.**
   - newsletter: the signature rule is missing once, in a run where the reply was cut. One run kept the stale president.
   - orders-api: one run missed the `stg2` correction (F6).

## Decision

Keep the change: there are clear gains on both tiers and no regression on memory_bench. Next: narrow "lasting fact" so one-off task details are not saved.
