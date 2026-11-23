# System leader vs scripted investigator (2026-11-22)

The System squad's sub-agents answered from a script (`squad-bench/fake_subagents.py`);
only the leader ran on a real model, `balanced` then `premium` (Sonnet 5.5).
omnis `develop` at `db28817`. How to run: `squad-bench/README-leader-fake.md`.

Two runs. The first showed that a leader holding `Bash` refutes scripted
evidence that is not on the host, so the scenarios were rewritten: the evidence
now sits on a host only the investigator can reach. **The second run is the
result; the first is kept below for what it showed.**

Three samples per cell: read the counts as indications, not rates.

## Second run — evidence out of the leader's reach

Records: `leader-fake-2026-11-v2-balanced.jsonl`, `leader-fake-2026-11-v2-premium.jsonl`.
Cost: **$0.57** (balanced $0.21, premium $0.37). 30 runs.

| Scenario | Leader | Delegated | Investigator calls | Own tool calls | Answer correct |
|---|---|---|---|---|---|
| `lf-unprompted` (this host, no sub-agent named) | balanced | 0/3 | 0 | 9, 12, 13 | 3/3 (says the logs are absent) |
| | premium | 2/3 | 1, 1, 0 | 3, 2, 5 | 3/3 |
| `lf-good` (correct finding) | balanced | 3/3 | 1, 1, 1 | 0 | 3/3 |
| | premium | 3/3 | 1, 1, 1 | 0 | 3/3 |
| `lf-fanout` (two questions) | balanced | 3/3 | **1, 1, 1** — one call for both | 0 | 3/3 |
| | premium | 3/3 | 2, 2, 2 — in parallel 3/3 | 0 | 3/3 |
| `lf-empty` (never any evidence) | balanced | 3/3 | **6, 4, 4** | 0, 2, 0 | 3/3 (states no cause) |
| | premium | 3/3 | **2, 2, 2** | 0 | 3/3 (states no cause) |
| `lf-reword` (off-topic, then the finding for a new request) | balanced | 3/3 | 2, 2, 2 | 0 | 3/3 |
| | premium | 3/3 | 2, 2, 2 | 0 | 3/3 |

"Answer correct" is the task's `facts` / `forbidden` check, re-scored after two
regex fixes found by reading the answers (a hyphenated "Out-of-Memory", and
"my search timed out" taken for an invented cause). The stored records carry the
verdicts of the rules as they were during the run.

### What it shows

1. **Which of the two conflicting rules wins depends on the model.** The
   leader's instruction says to re-task a failing sub-agent with different
   guidance; the shared block says to stop after two unhelpful attempts.
   - `premium` stops after **two** calls, 3 of 3. Its second request asks the
     investigator to confirm which host it read, then it tells the user what it
     could not establish.
   - `balanced` keeps going: **4 to 6** calls, each worded differently (no
     near-repeat), down to "This is your ONLY request… ls -la /var/log/". It
     follows "re-task with different guidance" and ignores "stop after two".
   Both end with an honest answer; `balanced` pays two to three times the calls.

2. **`balanced` does not fan out.** Given two unrelated questions it sends one
   combined request, 3 of 3. `premium` sends two calls in the same response, 3
   of 3. The "one call per independent question" rule is not followed on
   `balanced`.

3. **`balanced` delegates only when told who has the access.** With the
   evidence on `batch-02` it delegates 12 of 12; asked about this host with no
   sub-agent named it never does (0 of 3 here, 0 of 12 in the first run).
   `premium` delegates unprompted 2 of 3.

4. **Both recover from an off-topic answer** with one genuinely different
   request, 6 of 6, and both use a correct finding as given.

5. **No repeated or near-repeated request in 54 runs** across both runs. The
   "an identical re-call repeats the result" failure did not occur.

### Limits

- Three samples per cell, one squad, two models.
- The scenarios name the investigator as the only one with access. That is what
  makes the evidence unreachable, and it means only `lf-unprompted` measures
  delegation by default.
- The cost shown for a faked agent is not zero (one token at a non-zero price).
  Negligible.

### What to do next

- **omnis, `balanced` leaders.** Three instruction rules are not followed on
  this tier: delegate by default, one call per independent question, stop after
  two unhelpful attempts. Either make them effective there (host-side, as was
  done for other rules a weak model ignores) or keep `premium` on leaders that
  must coordinate.
- **omnis, the two conflicting rules.** `premium` already resolves them as
  "one real re-task, then stop and say what is unverified". Writing that single
  rule in both places would remove the conflict.
- **Bench.** Extend to `k8s_leader` and `coder`, and raise the sample count
  before turning any of these counts into a rate.

## Third run — rewritten System leader instruction (2026-11-23)

omnis branch `fix/system-leader-delegation` (`c03fefd`) rewrites the leader's
delegation rules: evidence questions go to the investigator first, one call per
independent question in the same response, one re-task then stop. Same
scenarios, same arms. Records: `leader-fake-2026-11-v3-balanced.jsonl` (5
samples), `leader-fake-2026-11-v3b-premium.jsonl` (3 samples). Cost $0.66.

| Scenario | balanced, old instruction | balanced, new | premium, old | premium, new |
|---|---|---|---|---|
| `lf-unprompted`: delegated | 0/3 | **0/5** | 2/3 | 3/3 |
| `lf-fanout`: investigator calls | 1, 1, 1 | **1, 1, 1, 1, 1** | 2, 2, 2 | 2, 2, 2 |
| `lf-empty`: investigator calls | 6, 4, 4 | **4, 4, 4, 4, 5** | 2, 2, 2 | 2, 2, 2 |
| `lf-good`: investigator calls | 1, 1, 1 | 1, 1, 1, 1, 2 | 1, 1, 1 | 1, 1, 1 |
| `lf-reword`: investigator calls | 2, 2, 2 | 2, 2, 2, 3, 3 | 2, 2, 2 | 2, 2, 2 |

- **The rewrite changes nothing on `balanced`.** It still never delegates
  unprompted, still sends one combined request for two questions, still makes
  four or five calls on empty evidence although the rule now says "re-task it
  ONCE". The claim made in `leader-fake-k8s-coding-2026-11.md`, that the System
  failure is "largely an instruction problem", is wrong in that form: the
  wording of the system instruction is not what `balanced` follows.
- **`premium` is unchanged**, 15 of 15 runs pass, and it delegated unprompted
  in 3 of 3 (2 of 3 before; too few samples to call it a gain).
- **Likely reason `balanced` delegates in the Kubernetes squad** (not verified):
  there the leader first loads the `k8s-triage` skill, whose text tells it to
  delegate evidence gathering. That instruction arrives in a tool result right
  before the decision, not at the top of a long system prompt. Every Kubernetes
  delegation in the logs follows a `load_skill`.

### A bench artefact found on the way

`leader-fake-2026-11-v3-premium.jsonl` shows one extra investigator call on
`lf-good` and `lf-fanout`. The scripted finding cited `run-2026-11-21.log`, and
the run took place on the 23rd: the leader re-tasked the investigator about
"last night". Scripted replies no longer carry a calendar date (a test forbids
it); `v3b` is the re-run. Keep `v3-premium` only as the record of the artefact.

### What to try next

A rule in the system instruction does not reach `balanced`. Two things did work
elsewhere in omnis for the same model: a short reminder placed next to the user
message (collection memory), and a rule delivered through a skill the agent
loads (Kubernetes). Either can be measured with this bench at about $0.30 a run.

## Fourth run — delegation reminder next to the user message (2026-11-23)

omnis branch `feat/turn-reminder` (`2d7a6d1`, from `develop` `db28817`: the
**old** leader instruction, unchanged). A new `agent.json` key, `turn_reminder`,
is appended to every typed user message of a squad root, as the memory reminder
is. On `leader`:

> [Delegation — before you act: a question that needs evidence from the machine
> (logs, files, processes, configuration, a remote host) goes to the
> 'investigator' sub-agent first, not to your own Bash, Read, Grep or Glob. Two
> independent questions = two 'investigator' calls in the same response. If a
> call comes back empty or off-topic, re-task it once with different guidance,
> then stop and say what is unverified.]

Records: `leader-fake-2026-11-v4-{balanced,premium}.jsonl`. `balanced` 5
samples, `premium` 3. Cost: **$0.64** for 40 runs.

| Scenario | balanced, third run (instruction) | balanced, reminder | premium, third run | premium, reminder |
|---|---|---|---|---|
| `lf-unprompted`: delegated | 0/5 | **5/5** | 3/3 | 3/3 |
| `lf-fanout`: calls, in parallel | 1 each, 0/5 | **2 each, 5/5** | 2 each, 3/3 | 2 each, 3/3 |
| `lf-empty`: calls | 4, 4, 4, 4, 5 | **3, 3, 3, 3, 2** | 2, 2, 2 | 2, 2, 2 |
| `lf-good`: calls | 1, 1, 1, 1, 2 | 1, 1, 2, 1, 1 | 1, 1, 1 | 1, 1, 1 |
| `lf-reword`: calls | 2, 2, 2, 3, 3 | 2, 2, 3, 2, 2 | 2, 2, 2 | 2, 2, 2 |

- **The reminder reaches `balanced` where the instruction did not.** Unprompted
  delegation 0/20 (all earlier runs) → 5/5; two independent questions now give
  two calls in the same response, 5/5; one call fewer on empty evidence.
  Answers pass the content checks 25/25; 24 of 25 runs pass the call gates (one
  `lf-good` run asked twice).
- **`balanced` delegates and also works itself.** In `lf-unprompted` every run
  made 4 to 10 `Bash` calls besides its single `investigator` call. "First" is
  followed; "not your own Bash" is not.
- **Empty evidence on `balanced`: 3 calls, not the 2 the reminder states**
  (4 of 5 runs).
- **`premium` is unchanged**, 15/15. In `lf-unprompted` it now asks the
  investigator twice (one re-task) before checking itself with 2-3 `Bash` calls,
  where it asked once before: the cost of "re-task it once".
- Five samples on one squad and one wording. Not measured: whether the reminder
  makes the leader delegate what it should do itself (a one-line answer, a file
  edit), and the Kubernetes and Coding leaders, which have no reminder.

## Fifth run — control arm, real squad, reworded reminder (2026-11-23)

Checks asked for before merging the reminder. Three additions:

- a **control arm in the same session** (`develop`, no reminder);
- `tasks-leader-fake-direct.json`: five requests the leader must answer itself
  (general knowledge, arithmetic, an explanation, writing a file, one word) —
  any `investigator` call is over-delegation;
- `tasks-leader-real.json`: the **real** System squad (no fake sub-agent) on
  four questions about the sandbox whose answer is known.

Records: `leader-fake-2026-11-v5-*` (control and first wording),
`leader-real-2026-11-{control,reminder}-*` and `-b-*` (first wording),
`leader-fake-2026-11-v6-*` and `leader-real-2026-11-v2-*` (second wording).
Cost of the whole run: **$3.83**.

### First wording: confirmed on fakes, two defects on the real squad

Scripted sub-agents, `balanced`, 5 samples: unprompted delegation 1/5 without
the reminder, 5/5 with; fan-out 1/5 → 5/5. No `investigator` call on the five
direct requests, either arm, either model (80 runs).

Real squad:

| | balanced, control | balanced, reminder | premium, control | premium, reminder |
|---|---|---|---|---|
| Correct answers | 36/36 | 31/36 | 12/12 | 12/12 |
| Turns ending with an empty reply | 0/36 | **5/36** | 0 | 0 |
| One-step lookup (`lr-count`): time | 3 s | 3 s | 3-4 s | **13-26 s**, delegated 3/3 |
| Cost per run | $0.0065 | $0.011 | $0.017 | $0.026 |

- `premium` delegated every one-step lookup (9/9), where it did them itself in
  3 s without the reminder.
- `balanced` ended 5 turns of 36 on an empty reply after its own tool call
  (4 on `lr-absent`, where `Glob` returns nothing). Likely the reminder's "then
  stop", read literally; the sessions were deleted, so this is unverified.

### Second wording

> [Delegation — a question that needs evidence from the machine beyond one
> quick lookup (several files, logs, a remote host, a cause to establish) goes
> to the 'investigator' sub-agent first, not to your own Bash, Read, Grep or
> Glob; a single quick lookup you may do yourself. Two independent questions =
> two 'investigator' calls in the same response. If the investigator's answer
> is empty or off-topic, re-task it once with different guidance and no more.
> Always end with a written answer to the user, saying what is unverified.]

omnis `feat/turn-reminder` at `8341849`.

| | balanced | premium |
|---|---|---|
| Scripted: unprompted delegation | 5/5 | 3/3 |
| Scripted: fan-out in parallel | 5/5 | 3/3 |
| Scripted: calls on empty evidence | 4, 4, 2, 3, 3 | 2, 2, 2 |
| Scripted: direct requests, `investigator` calls | 0 in 25 | 0 in 15 |
| Real: correct answers | 35/36 | 12/12 |
| Real: empty replies | 0/36 | 0/12 |
| Real: one-step lookups delegated | 0/27 | 0/9 |
| Real: one-step lookup time | 3-5 s | 3-8 s |
| Real: two-question task (`lr-two`) | delegated 7/9, 31-49 s | delegated 3/3, 29-45 s |

- Both defects of the first wording are gone; the gains on the scripted bench
  are kept.
- **What it costs:** the two-question task on a 37-line sandbox takes 30-49 s
  through two investigator calls, against 5-8 s when the leader reads the two
  files itself (`balanced` control; `premium` control already delegated it
  2/3). The answers are the same.
- **Not fixed:** `balanced` still makes 2 to 4 calls on empty evidence (control:
  2 to 5), and still runs 2-3 `Bash` calls beside its delegation in
  `lf-unprompted` (first wording: 4-10).
- One `balanced` real run (1/36) ended after its acknowledgement line with no
  answer. Control: 0/36.
- Limits: one squad, small sandbox tasks, 3 to 9 samples per cell.

## First run — evidence absent from the host

Records: `leader-fake-2026-11-balanced.jsonl`, `leader-fake-2026-11-premium.jsonl`.
Cost $0.55. 24 runs, scenarios as first written (the scripted findings cited
files under `/var/log/…` on the bench host, where they do not exist).

| Scenario | Leader | Delegated | Investigator calls | Own tool calls |
|---|---|---|---|---|
| `lf-good` | balanced | 0/3 | 0 | 6, 29, 13 |
| | premium | 3/3 | 1, 1, 1 | 0, 4, 4 |
| `lf-fanout` | balanced | 0/3 | 0 | 6, 4, 8 |
| | premium | 3/3 | 2, 2, 2 (parallel 3/3) | 0, 0, 0 |
| `lf-empty` | balanced | 0/3 | 0 | 5, 5, 7 |
| | premium | 3/3 | 1, 1, 1 | 2, 1, 1 |
| `lf-reword` | balanced | 0/3 | 0 | 3, 3, 9 |
| | premium | 2/3 | 0, 2, 2 | 3, 3, 3 |

What it showed, and still stands:

- On `balanced` the leader never delegated (0 of 12) and investigated with its
  own `Bash`, although its instruction says "DELEGATE BY DEFAULT".
- The `premium` leader checks its sub-agent's claims: in 4 of the 5 runs where
  the scripted finding cited a file, it looked for the file, did not find it,
  and reported the finding as unverified. Good behaviour — and the reason the
  scenarios had to change.
- `quality_gate` was unreliable in that run: it passed answers that quoted the
  finding while disowning it.
- Runs of 130-200 s were the leader's own filesystem-wide searches timing out.
