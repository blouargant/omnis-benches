# Collection memory: narrowed reminder (2026-11-10)

## What was tested

omnis `develop` (c123d5d, per-message reminder) plus two uncommitted wording changes. The goal was to stop high saving the details of the task at hand (forbidden item F2 in the newsletter conversation).

- **Reminder.** "gives a lasting fact" became "gives a fact later conversations will need", followed by "Never save the details of the task at hand (one event's date, place or time, one draft's content)."
- **Rules (`collmem.Rules`).**
  - The `project` line now says the details of the task at hand are not such facts.
  - The "Do not save" list now names "a one-off detail of this conversation's task".

Harness and setup:

- `memory_quality.py` (orders-api + newsletter) ×3, judged by Fable 5.2.
- `memory_bench.py` ×3.
- Balanced `update` and `forget` were run 3 more times to check the failures below.
- One server per tier (`setup-ab.sh`, `MODEL=ref:<tier>`).
- Raw records: `memory-narrow-2026-11-10.jsonl` and `memory-narrow-2026-11-10-recall.jsonl` (rerun label `narrow-balanced-rerun`).
- Baseline: `memory-remind-2026-11-10.md`.

## Result (mean of 3)

| Tier | Conversation | recall | precision | applied | judge /10 | cost |
|---|---|---|---|---|---|---|
| high, reminder | newsletter | 1.00 | 0.91 | 0.83 | 7.7 | $0.51 |
| high, narrowed | newsletter | 1.00 | **1.00** | **0.92** | **8.7** | $0.17 |
| balanced, reminder | newsletter | 0.83 | 1.00 | 0.58 | 5.7 | $0.59 |
| balanced, narrowed | newsletter | 0.83 | 1.00 | 0.67 | 6.7 | $0.18 |
| high, reminder | orders-api | 1.00 | 1.00 | 0.94 | 9.0 | $0.79 |
| high, narrowed | orders-api | 1.00 | 1.00 | **1.00** | 9.0 | $0.25 |
| balanced, reminder | orders-api | 0.93 | 1.00 | 0.89 | 8.0 | $0.79 |
| balanced, narrowed | orders-api | 0.87 | 1.00 | 0.89 | 7.3 | $0.32 |

The cost columns are not comparable: the earlier report gives cost per conversation including the judge, this one gives omnis only.

memory_bench:

| Tier | Reminder | Narrowed |
|---|---|---|
| high | 15/15 | **15/15** |
| balanced | 14/15 | 11/15 (rerun of update + forget: 4/6) |

## Findings

1. **The over-saving on high is gone.** No run saves the outing details; precision is 1.00 in all 6 high conversations. High also applies the stored rules more (newsletter 0.83 → 0.92, orders-api 0.94 → 1.00).
2. **Balanced is unchanged within noise.**
   - newsletter: up 1 point.
   - orders-api: the 1-point drop is one run (overall 4) that again missed the `stg2` correction (F6), a miss already seen in the previous report.
3. **Balanced memory_bench failures are mostly cut replies, not memory.**
   - In 6 runs of `update`, 4 failed. In 3 of these 4, one reply was cut at the 32,768-token output limit. In one more, step A asked a question instead of saving.
   - `forget` failed 2 of 6: the model said "Noté." without deleting, or deleted without the memory going away. The reminder does not mention `memory_delete`.
4. **New problem: Balanced sometimes writes until the output limit.**

   | Run | Cut replies on balanced memory_bench steps |
   |---|---|
   | guard (no reminder) | 0 of 42 |
   | reminder | 2 of 42 |
   | narrowed | 2 of 42 |
   | narrowed rerun | 2 of 18 |

   The server log shows 10 such cuts during the narrowed run, across all scenarios. High shows none.
   - It appears with the reminder, not with this change.
   - 8 manual tries of the `update` prompts did not reproduce it. The content of a cut reply was not captured, because the bench deletes its sessions.

## Decision

Keep the narrowed wording: it fixes the high over-saving and costs nothing measurable on balanced.

Next:

1. Capture a cut Balanced reply (`-d` server log, or keep the bench sessions) to see what the model loops on.
2. Add "if the message says to forget something, call memory_delete" to the reminder.
