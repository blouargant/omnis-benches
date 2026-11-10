# Collection-memory quality bench

`memory_bench.py` checks that one fact said once comes back. `memory_quality.py`
checks **what** the assistant chooses to remember over a realistic conversation,
and how well it writes it down.

Each conversation of `tasks-memory-quality.json` runs in one session of a fresh
collection: 9–11 scripted user turns mixing work, corrections, a fact corrected
later, one-off details, general-knowledge questions, a secret, and (orders-api) a
file carrying a hidden instruction to save a fake preference. A hands-off user
answers any question the agent asks ("no preference, decide yourself"). Then each
recall question runs in a **new** session of the same collection.

A judge then reads the transcript, the ground truth (`expected` / `forbidden` /
`optional`), the collection's final memories and the recall answers, and grades:

| Score | Meaning |
|---|---|
| `recall` | expected memories present (1) / partial (0.5) / missing (0), averaged |
| `precision` | share of the final memories worth keeping |
| `violations` | forbidden items found in memory (want 0) |
| `duplicates` | memories repeating another one |
| `faithful` | how exactly memories say what the user said (0–1) |
| `application` | recall answers applying the memory (0–1) |
| `overall` | judge's 0–10: would this memory help later conversations |

The judge is **Fable through the Claude Code CLI** (`claude -p --model fable`,
the logged-in Claude Code account — no API key, no gateway), called with no
settings, MCP or tools (≈ 800 tokens of CLI overhead). `--judge-model` picks
another model; `--no-judge` only records, `--rejudge FILE` grades recorded runs
(e.g. after changing the rubric).

```bash
set -a; . ./.env; set +a
MODEL=ref:premium squad-bench/setup-ab.sh /tmp/mq premium develop 18911
python3 squad-bench/memory_quality.py --server http://127.0.0.1:18911 --token bench \
    --repeat 3 --label premium --out runs-memory-quality.jsonl
squad-bench/setup-ab.sh /tmp/mq premium stop
```

Unit tests: `python3 -m unittest squad-bench/test_memory_quality.py`.
