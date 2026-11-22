# Fake sub-agents for squad-bench — design

Date: 2026-11-22. Branch: `bench/fake-subagents` (from `main`).

## Why

A leader's behaviour towards its sub-agents is specified in prompts and never
measured. Real sub-agents cannot be used to measure it: they fail when they
happen to, not when a test needs them to, and their cost and variance hide the
leader's own.

The idea comes from "Language Model Harnesses Can Be Compositional
Generalizers" (Zhang, Chakraborty, Khattab, 2026), which trains a root model
against sub-calls replaced by a noisy oracle. Here nothing is trained: the same
trick isolates the leader for benchmarking.

First target: how the **System leader** (`leader`) reacts to what
`investigator` returns. Two shipped rules pull in opposite directions and
nobody knows which wins:

- `registry/agents/leader/instruction.md`: when a sub-agent fails, "do not take
  over at once: diagnose, then re-task it with genuinely different guidance".
- the shared sub-agent block (`buildSubAgentCapabilitiesBlock`): an identical
  re-call repeats the result; after two unhelpful attempts, stop.

## Goals

- Run a squad whose sub-agents answer from a script, while the leader runs on a
  real model.
- Record what the leader sent to each sub-agent: number of calls, whether
  requests were repeated or reworded, how many calls overlapped.
- Four scenarios on the System leader, with pass/fail checks.

## Non-goals

- No change to omnis. Everything lives in `omnis-benches` (repo policy).
- Kubernetes and Coding leaders.
- Random noise. Scripts are fixed, so a run differs only by the leader.
- Fixing the two conflicting rules. This work reports what happens.

## Anti-goal

A bench that passes because the fake is too helpful. A fake reply must never
contain more than the scenario says, and an unscripted call gets
"No evidence found.", not a guess.

## Approaches considered

1. **Fake model server (chosen).** Sub-agents keep their real omnis wiring but
   their `model_ref` points at a local OpenAI-compatible server that answers
   from the task's script. No omnis change; `prompt-size/fake_server.py` already
   proves the mechanism.
2. **Stub sub-agent inside omnis.** A test-only tool replacing the agenttool
   wrapper. Rejected: bench code in omnis is against the repo policy, and it
   would bypass the wrapper whose behaviour (session handles, fan-out) the
   leader actually sees.
3. **Replay recorded real answers.** Rejected: a failure cannot be ordered on
   demand, which is the point.

## Design

### `squad-bench/fake_subagents.py` — the server

OpenAI-compatible, stdlib only, streaming and non-streaming, adapted from
`prompt-size/fake_server.py`. `fake_subagents.py PORT`.

- **Who is calling**: each faked agent has its own model id, `fake-<agent>`.
  The request's `model` field names the agent.
- **What was asked**: the text of the last `user` message of the request.
  Builder: confirm with one probe run what a sub-agent request looks like
  (including a `resume_session` call) before fixing the extraction.
- **Control endpoints** (not part of the OpenAI surface):
  - `POST /scenario {"task": id, "script": {...}}` sets the script and clears
    the log.
  - `GET /calls` returns the log:
    `[{agent, n, request, rule, started_ms, ended_ms}]`.
- **Script**: `{"<agent>": [rule, ...]}`. A rule has `reply` (text) and
  optionally:
  - `times`: how many times it may be used (default unlimited);
  - `if_new_request: true`: usable only when the request differs from every
    earlier request of that agent in this task (whitespace and case ignored);
  - `status`: answer with this HTTP error instead of a reply;
  - `delay_ms` (default 300, so overlapping calls are observable).
  The first usable rule wins. No usable rule, or an agent absent from the
  script: reply "No evidence found."
- It never returns a tool call. Usage is a small fixed number.

### `squad-bench/fake_overlay.py` — the config overlay

`fake_overlay.py --sys <omnis config dir> --fake a,b,c --port N
[--leader <agent> --leader-model <catalogue ref>] --out <dir>` writes an
overlay for the user layer, used as `OVERLAY=` with `setup-ab.sh MODEL=tiered`:

- `models.json`: provider `fake` (`openai_compat`,
  `http://127.0.0.1:N/v1`), one model `fake-<agent>` per faked agent with zero
  prices, and `override_model_enabled: false` — the single-model override would
  put the fakes back on a real model.
- `registry/agents/<agent>/agent.json`: `{"model_ref": "fake-<agent>"}`.
- With `--leader-model`: the leader's `agent.json` gets that `model_ref`.

### `bench.py`

- New flag `--fake URL`. Before a task that has a `fake` block, POST it to
  `/scenario`; after the task, GET `/calls` and add to the record:
  `fake: {calls: {agent: n}, distinct_requests: {agent: n}, repeats: {agent: n},
  max_parallel: n, requests: [...]}` (request text cut at 500 chars).
- A task with a `fake` block and no `--fake` is an error, not a silent real run.

### `scoring.py`

New pure function `check_fake(expect_fake, fake)` with unit tests. A task may
declare, per agent: `min_calls`, `max_calls`, `min_distinct`, `max_repeats`,
and for the whole task `min_parallel`. The record gets `fake_gate` (bool) and
the list of failed checks. Answer content keeps using `facts` and `forbidden`.

### `tasks-leader-fake.json` — four scenarios, squad `system`, `cwd: sandbox`

Each question is about evidence the leader cannot reach itself (logs of a
service that does not exist in the sandbox), so the only source is the fake.

| id | Script for `investigator` | Passes when |
|---|---|---|
| `lf-good` | one correct, cited finding | 1 call; answer states the finding |
| `lf-fanout` | two findings, one per question | 2 calls, `min_parallel` 2; both findings in the answer |
| `lf-empty` | always "No evidence found." | at most 3 calls, no repeated request; answer says it is unverified and states no cause |
| `lf-reword` | first reply off-topic; correct finding only for a new request | at least 2 distinct requests; answer states the finding |

The exact prompts, findings and regexes are the builder's.

## Left to the builder

- Wording of the prompts and replies, and the `facts` / `forbidden` regexes.
- How the server computes `max_parallel` from the log.
- Unit tests: script rules (in-process), `check_fake`, the overlay.
- A README section in `squad-bench/README.md`.

## Done when

- Unit tests pass.
- The four scenarios run end to end against a real omnis-server, three samples
  each, with the leader on `premium` and on `balanced`.
- A short report in `reports/` gives the pass rate per scenario and model, and
  says which of the two conflicting rules the leader follows.

## Risks

- The leader holds `Bash` and the arm runs with `bypassPermissions` (as every
  `setup-ab.sh` arm does). Prompts ask for read-only investigation only.
- `feat/adoption-step0` also changed `bench.py`; expect a merge conflict there.
