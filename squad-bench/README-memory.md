# Collection-memory bench

Does a correction said once stick? `memory_bench.py` runs the scenarios of
`tasks-memory.json` against an omnis-server with collection memory (omnis ≥
240711f): each scenario in fresh collections, one prompt per step (a new step
session = a new chat in that collection), then reads the collection's memories
back (`GET /api/collections/:name/memories`) and checks answers and memories.

```bash
set -a; . ./.env; set +a
MODEL=ref:balanced squad-bench/setup-ab.sh /tmp/mb balanced develop 18902
python3 squad-bench/memory_bench.py --server http://127.0.0.1:18902 --token bench \
    --repeat 3 --label balanced --out runs-memory.jsonl
squad-bench/setup-ab.sh /tmp/mb balanced stop
```

`MODEL=ref:<name>` (new in `setup-ab.sh`) forces that catalogue model, with its
own prices, onto every agent. Checks: `step<N>_answer` / `step<N>_answer_not`
(regex on that step's answer), `memory_saved` / `memory_absent`,
`stale_value_gone`, `no_duplicate`, `memory_count`. Unit tests:
`python3 -m unittest squad-bench/test_memory_bench.py`. First run:
`reports/collection-memory-2026-11-09.md`.
