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
| `if_new_request` | only for a request unlike any this agent received before in the task: case and spacing are ignored, and a request at least 90 % similar to an earlier one (an added "please", "try again") is not new |
| `delay_ms` | wait before answering (default 300, so parallel calls overlap) |

`expect_fake` checks the call log: per agent `min_calls`, `max_calls`,
`min_distinct`, `max_repeats` (identical requests), `max_near_repeats`
(requests at least 90 % similar to an earlier one, identical ones included);
for the task `min_parallel` (calls open at the same time, all agents together). The answer's content is still judged by `facts` and `forbidden`.

## What the record gains

`fake: {calls, distinct_requests, repeats, near_repeats, max_parallel,
requests}` (each request cut at 500 chars), `fake_gate` (true / false / null
when the task expects nothing) and `fake_failed` (e.g.
`["investigator.max_near_repeats"]`). With `--fake`, every task gets these,
scripted or not (an unscripted task's sub-agents all answer the default). When
the log cannot be read — the server died, or another run replaced the scenario
— the record carries `fake_error` and `fake_gate` is false: it is never scored.

## Shipped scenarios (`tasks-leader-fake.json`, System leader)

`lf-unprompted` asks about this host and names no sub-agent. The four others put
the evidence on a host the prompt says only the investigator can reach
(`batch-02`), so the leader can neither find nor refute it with its own tools.

| id | The investigator returns | Passes when |
|---|---|---|
| `lf-unprompted` | never any evidence | the leader delegated at least once without being told to |
| `lf-good` | a correct, cited finding | one call; the answer states it |
| `lf-fanout` | one finding per question | two calls open at once; both findings |
| `lf-empty` | never any evidence | 1 to 3 calls, none a near-repeat; the answer says so and states no cause |
| `lf-reword` | off-topic first, the finding only for a reworded request | two distinct requests; the answer states it |

## Other squads

Same scenario shapes for two more leaders; one arm can serve all three files
(fake every member of the three squads, and pass
`--leader leader,k8s_leader,coder --leader-model balanced` to move the leaders).

| File | Leader | Evidence out of reach because |
|---|---|---|
| `tasks-leader-fake-k8s.json` | `k8s_leader` | it is on a cluster only `k8s_investigator` has a context for; no scenario asks for a cluster change |
| `tasks-leader-fake-coding.json` | `coder` | it is the documentation of a library the coder does not know, and it has no web tool; `cd-review` runs the review loop against a scripted reviewer |

Members to fake: `k8s_investigator,k8s_editor,k8s_cleaner` and
`code_scout,code_docs,reviewer,refactorer,agentmd_reviewer`. Results:
`reports/leader-fake-k8s-coding-2026-11.md`.

## Limits

- A scripted source must be one the sub-agent could plausibly reach: asked about
  an internal GitLab library, the premium coder rightly did not ask its web
  researcher.
- `near_repeats` flags the two requests of a fan-out when they differ only by a
  name; do not gate a fan-out scenario on it.

- **Read the `lf-empty` answers by hand.** "States no cause" is judged by a
  list of regexes; it catches the common inventions, not all of them.
- `lf-reword` also passes when the leader sends two different requests at once;
  check in `fake.requests` that the second came after the first reply.
- A time limit on the arm (`OMNIS_TURN_MAX_SECONDS`) appends a note to every
  sub-agent request and breaks the repeat counts; `setup-ab.sh` sets none.
- Keep scripted evidence out of the leader's reach: when it cited files absent
  from the bench host, a careful leader checked and disowned it (first run in
  `reports/leader-fake-2026-11.md`).
- Only `lf-unprompted` measures delegation by default; the other prompts name
  the investigator.
- omnis retries an HTTP 5xx, so a `status` rule is logged once per attempt.
- The leader keeps its own tools (`Bash`, `Read`…) and the arm runs with
  `bypassPermissions`: keep prompts read-only.
- A task with a `fake` script and no `--fake` stops the bench before it starts.

## Companion task files

- `tasks-leader-fake-direct.json` — requests the System leader answers itself;
  an `investigator` call there is over-delegation (gate: 0 calls). Run it with
  `--fake` like the others.
- `tasks-leader-real.json` — the real System squad (no `--fake`, no fake
  overlay) on small questions with a known answer: checks that a delegation
  change keeps answers correct and what it costs in time and money.
