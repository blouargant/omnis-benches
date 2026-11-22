# Leader vs scripted sub-agents

Measures how a squad **leader** delegates, with its sub-agents replaced by a
script. The sub-agents keep their omnis wiring, but their model is
`fake_subagents.py`, a local server that answers from the current task's
script and logs every call; the leader runs on a real model. A run then differs
only by what the leader did, and a sub-agent failure happens when the task
orders it. Design: `docs/superpowers/specs/2026-11-22-fake-subagents-design.md`.

## Run it

From the `omnis-benches` root, with the gateway credentials in the environment
(`set -a; . ./.env; set +a`) and an omnis checkout at `../omnis`:

```bash
W=$(mktemp -d)
python3 squad-bench/fake_subagents.py 18770 &          # the fake model server
F=investigator,summariser,helper,linux_admin           # the System squad's members
python3 squad-bench/fake_overlay.py --sys ../omnis --fake $F --port 18770 --out $W/ov
MODEL=tiered OVERLAY=$W/ov squad-bench/setup-ab.sh $W arm develop 18801
python3 squad-bench/bench.py --server http://127.0.0.1:18801 --token bench \
  --tasks squad-bench/tasks-leader-fake.json --suite --repeat 3 --nonce \
  --fake http://127.0.0.1:18770 --out runs.jsonl
squad-bench/setup-ab.sh $W arm stop
```

- `MODEL=tiered` is required: the single-model override would put the fakes back
  on a real model (the overlay also switches it off).
- To move the leader to another catalogue model, add
  `--leader leader --leader-model balanced` to `fake_overlay.py`.
- The fake server holds **one scenario at a time**: run arms one after the other.
- `curl -s http://127.0.0.1:18770/calls` shows what the sub-agents were asked in
  the last task.

## A task

```json
{"id": "lf-reword", "squad": "system", "cwd": "sandbox", "prompt": "…",
 "fake": {"investigator": [{"times": 1, "reply": "off-topic"},
                           {"if_new_request": true, "reply": "the finding"},
                           {"reply": "off-topic"}]},
 "facts": [{"id": "cause", "required": true, "match": "/out of memory|oom/"}],
 "expect_fake": {"agents": {"investigator": {"min_distinct": 2}}}}
```

`fake` maps an agent to its rules. The first usable rule answers; with none, or
for an agent absent from the script, the reply is `No evidence found.`

| Rule field | Meaning |
|---|---|
| `reply` | the text the sub-agent returns |
| `status` | answer with this HTTP error instead |
| `when` | the leader's request must match (`/regex/` or substring) |
| `times` | how many times the rule may be used |
| `if_new_request` | only for a request this agent has not received before in the task (case and spacing ignored) |
| `delay_ms` | wait before answering (default 300, so parallel calls overlap) |

`expect_fake` checks the call log: per agent `min_calls`, `max_calls`,
`min_distinct`, `max_repeats`; for the task `min_parallel` (calls open at the
same time). The answer's content is still judged by `facts` and `forbidden`.

## What the record gains

`fake: {calls, distinct_requests, repeats, max_parallel, requests}` (each
request cut at 500 chars), `fake_gate` (true / false / null when the task
expects nothing) and `fake_failed` (e.g. `["investigator.max_repeats"]`).

## Shipped scenarios (`tasks-leader-fake.json`, System leader)

| id | The investigator returns | Passes when |
|---|---|---|
| `lf-good` | a correct, cited finding | one call; the answer states it |
| `lf-fanout` | one finding per question | two calls open at once; both findings |
| `lf-empty` | never any evidence | at most 3 calls, none repeated; the answer says so and states no cause |
| `lf-reword` | off-topic first, the finding only for a reworded request | two distinct requests; the answer states it |

## Limits

- omnis retries an HTTP 5xx, so a `status` rule is logged once per attempt.
- The leader keeps its own tools (`Bash`, `Read`…) and the arm runs with
  `bypassPermissions`: keep prompts read-only.
- A task with a `fake` script and no `--fake` stops the bench before it starts.
