# Agent lessons: first bench (2026-11-20)

## What was tested

omnis `feat/agent-lessons` at `ba96fa5`. When an agent's tool call fails and a
later call of the same tool in the same run succeeds, the host writes a one-line
lesson (`$OMNIS_HOME/lessons/<agent>/<id>.md`). When the same agent hits the same
error again (tool + normalised error text), the tool result gets a `lesson` note:
the lesson and the arguments that worked. A lesson seen 3 times across 2 sessions
goes into the agent's system prompt. A lesson whose hint fails 3 times in its last
5 hints is retired. `OMNIS_LESSONS=false` turns everything off.

Setup:

- Two `setup-ab.sh` arms built from `ba96fa5`, every agent on `balanced`
  (`MODEL=ref:balanced`): **on** (default) and **off** (`OMNIS_LESSONS=false`,
  passed through the environment; `setup-ab.sh` starts the server with `env`, which
  keeps inherited variables, and the variable was checked in the server process).
  The lesson writer uses `eval_model_ref` (`hosted`); the single-model override
  does not touch it.
- `squad-bench/tasks-lessons.json`: six Coding-squad tasks, see
  `squad-bench/README-lessons.md`. Four ask for an edit then `lsp_diagnostics`,
  hoping the agent calls the deferred tool by name with `file_path` (its schema
  wants `file`). It did so in 3 of the 20 sessions of these four tasks (see
  Result). Two name a file path that does not exist (`limiter/rate.go`,
  `cmd/server.go`): an error every time, but caused by the prompt.
- Each arm ran the six tasks twice on the same `OMNIS_HOME`, one sample per task.
  The on arm ran a third time once both promoted lessons were in place. Then
  `tasks-prompt-ab.json` once per arm.
- Runner: `reports/agent-lessons-2026-11-20/run_lessons.py`. Each task runs in a
  fresh copy of its fixture. Tool errors are counted from the session's
  conversation file, root and sub-agent calls, with omnis's own rule
  (`classifyToolFailure`). `bench.py` only counts sub-agent errors. A result with a
  `lesson` key is a delivered hint. Cost is the agents' cost from `turn_usage`; the
  lesson writer's call is not in it (one `hosted` call per new lesson).

Raw records, in `reports/agent-lessons-2026-11-20/`:

- `runs-on.jsonl`, `runs-off.jsonl`: the runner's records;
- `results.json`, `tables.md`: their re-scoring with `run_lessons.py --merge`,
  from which the tables below are taken;
- `runs-<arm>-lessons-<arm>-run<n>.json`: the lessons snapshot after each run;
- `lessons-files/`: the four lesson files;
- `promptab-*.jsonl`, and the probe passes `probe*.jsonl`.

**Checks tightened after the runs.** The first checks verified the edit but not
that `lsp_diagnostics` ran, and `read-missing-limiter` passed on the word "burst",
which a model can say without reading the file. Now each `lsp-diag-*` task also
needs a successful `lsp_diagnostics` call, `read-missing-limiter` needs `b.last`
(the bucket's timestamp field, only in the fixture), and the unused `expect`
values are gone. The existing records were re-scored (no re-run): no `correct`
changed.

## Probe passes

A first pass with lessons off checked that each task produces an error. Most of the
first ideas gave none on `balanced`:

| Tried | What balanced did |
|---|---|
| `Edit`, the obvious one-line `old_string` appears twice | Read the file first and gave a unique block in the dedicated task (0/1). On the same file, inside `lsp-diag-timeout`, it happened in the probe (1/1) and in 3 of 5 bench sessions |
| `Edit` with a space-indented block quoted in the prompt | Read the file first, used the tabs |
| `Grep` for `parseConfig(` and `*args` | Escaped the regex itself |
| `lsp_references`, `lsp_document_symbols` | Called `tool_search` first, so it had the schema |
| `Glob` limited to a directory | Put the directory in the pattern; once ended the turn with an empty reply |

The one error `balanced` made on its own was `lsp_diagnostics {"file_path": …}`,
in 2 of the 5 probe sessions that called `lsp_diagnostics` (once unprompted):
`lsp_*` tools are deferred on `coder`, and when it calls one by name without
`tool_search` it has no schema and uses the fs tools' parameter name. That error
gave the four `lsp-diag-*` tasks. The two `read-missing-*` tasks are provoked by
the prompt (a user who misremembers a path).

## Result

Totals, six tasks per cell, one sample each:

| Arm | Run | Tool errors | Tool calls | Hints delivered | Cost | Wall | Correct |
|---|---|---|---|---|---|---|---|
| off | 1 | 3 | 39 | 0 | $0.101 | 54 s | 6/6 |
| off | 2 | 4 | 39 | 0 | $0.088 | 38 s | 6/6 |
| on | 1 | 5 | 33 | 1 | $0.092 | 48 s | 6/6 |
| on | 2 | 4 | 38 | 4 | $0.108 | 64 s | 6/6 |
| on | 3 | 3 | 34 | 2 | $0.105 | 58 s | 6/6 |

No sub-agent error in any run (the prompts say not to delegate; nothing was
delegated). The on and off arms ran at the same time, so wall times compare.

Per task (errors / calls; the tool that failed):

| Task | off 1 | off 2 | on 1 | on 2 | on 3 |
|---|---|---|---|---|---|
| lsp-diag-timeout | 0 / 5 | 1 / 7 Edit | 1 / 7 Edit | 1 / 7 Edit (hinted) | 1 / 10 todo_write |
| lsp-diag-worker | 0 / 6 | 0 / 7 | 1 / 6 lsp_diagnostics | 1 / 4 lsp_diagnostics (hinted) | 0 / 5 |
| lsp-diag-svc | 0 / 5 | 0 / 6 | 0 / 5 | 0 / 5 | 0 / 7 |
| lsp-diag-limiter | 1 / 11 Read | 1 / 10 Read | 1 / 5 lsp_diagnostics (hinted) | 0 / 9 | 0 / 4 |
| read-missing-limiter | 1 / 5 Bash | 1 / 4 Read | 1 / 5 Bash | 1 / 4 Read (hinted) | 1 / 4 Read (hinted) |
| read-missing-svc | 1 / 7 Read | 1 / 5 Read | 1 / 5 Read | 1 / 9 Read (hinted) | 1 / 4 Read (hinted) |

`tasks-prompt-ab.json`, once per arm (the on arm with both promoted lessons in
`coder`'s prompt):

| Task | off | on |
|---|---|---|
| search-single, search-multi, symbol-fields, docs-lookup | 4/4 | 4/4 |
| router-web, system-count, helper-docs | 3/3 | 3/3 |
| web-lookup (fact gate) | pass | pass |
| web-canary (fact gate) | pass | **fail** (2 730 mm instead of 2 738) |
| Cost | $0.131 | $0.098 |

Nothing points to lessons in the web-canary miss: no lesson exists for the
Knowledge squad (the only lesson directory written was `coder`'s), and the two arms
diverged on the first source chosen (on: 1 search, 1 fetch of en.wikipedia, 2 730
mm; off: 1 search, 4 fetches of fr.wikipedia, 2 738 mm). But this is one sample per
arm, not repeated, so it is not shown either. Correctness did not drop on the
Coding tasks.

## Lessons written

All by `coder`:

| Id | Tool | State after run 3 | seen | hinted | recovered | repeated | seen_in_prompt |
|---|---|---|---|---|---|---|---|
| 675f68476589 | lsp_diagnostics | prompt (since run 2) | 3 | 2 | 2 | 0 | 0 |
| fb21da2a7151 | Read | prompt (since run 2) | 5 | 4 | 4 | 0 | 2 |
| 830cc3865a87 | Edit | hint | 2 | 1 | 1 | 0 | 0 |
| 96fadefdeefe | todo_write | hint (written in run 3) | 1 | 0 | 0 | 0 | 0 |

Texts (cue → lesson):

- **lsp_diagnostics**: "lsp_diagnostics rejects 'file_path' argument" → "Use 'file' instead of 'file_path' to specify the file for diagnostics." Worked: `{"file":"worker.go"}`.
- **Read**: "File not found when using an incorrect subdirectory in the file path" → "Use the correct relative file path relative to the current working directory." Worked: `{"file_path":"server.go"}`.
- **Edit**: "old_string appears multiple times in the file" → "Include surrounding context or set replace_all to true to make the old_string unique." Worked: the two-line block with the function header.
- **todo_write**: "todo_write expects tasks as a list of strings, not objects" → "When calling todo_write, ensure the "tasks" argument is a JSON array of strings, not an array of objects containing content and status fields." Worked: the list of strings.

A delivered hint, as the agent saw it (an `Edit` error result):

```
{"lesson": "Learned from an earlier error with this tool: Include surrounding context or set replace_all to true to make the old_string unique.\nArguments that worked then: {\"file_path\":\"handlers.go\", …}",
 "result": "Error: old_string appears 2 times in …/handlers.go — set replace_all:true or provide more context to make it unique"}
```

## What the numbers show

- **The mechanism works end to end.** Episodes were detected, lessons written
  (one `hosted` call each, within seconds), hints attached to the matching error
  in later sessions, in run 1 already (`lsp-diag-limiter` got the lesson written
  in `lsp-diag-worker`), counters updated, two lessons promoted at `seen = 3`. The
  off arm wrote no lesson file and added no hint. Each hint was followed by a
  working call of the same tool (`recovered` 7, `repeated` 0), so no lesson was
  retired.
- **Lesson quality varies.** The two lessons about a tool's schema
  (`lsp_diagnostics`, `todo_write`) say something the agent did not know. The
  `Edit` lesson repeats the advice already in the error message. The `Read` lesson
  says nothing usable ("use the correct path").
- **The prompt lessons did not prevent the `Read` error**, as expected: the wrong
  path comes from the user's request. That lesson is now in `coder`'s prompt on
  every call. `seen_in_prompt` is at 2, so one more occurrence demotes it to a hint.

## What the numbers do not show

One sample per cell: every difference below is indicative, not significant.

- **Fewer errors with lessons is not shown.** On went 5 → 4 → 3, off went 3 → 4.
  The `lsp_diagnostics` error, the one the agent makes on its own, happened in 2 of
  4 sessions in on run 1, 1 in run 2, and 0 in the 6 sessions after promotion. But
  it also happened in 0 of 8 off sessions, and in 2 of the 5 probe sessions that called it. Its
  base rate is too low and too unstable for 4 sessions per run to show a drop.
- **A hint helping is not shown.** `recovered` counts the next call of the tool
  succeeding, and the agent recovers from these errors without a hint too: every
  off session that hit one still finished correctly. Calls after a hint
  were not fewer: `read-missing-*` took 4 and 9 calls with a hint in run 2 against
  4 and 5 without.
- **Cost:** within noise (on runs $0.092–0.108, off $0.088–0.101). A hint adds
  ~100–400 tokens to one tool result; the prompt block is two lines.

## Findings on the feature

1. **What counts as an error leaves out common cases.** `run_tests` failures
   (`run_tests: …`) and a `Bash` command that exits non-zero with output are not
   errors, so they never give a lesson. A silent non-zero `Bash` (`Error: exit
   status 1`, e.g. `find … 2>/dev/null` with no match) is one. A
   `memory_read` of a name that does not exist (`{"error":"no memory named …"}`)
   also counts (seen in a probe pass), which can produce a lesson about
   memory.
2. **The main source of agent-made errors here is the deferred-tool trap**: a
   deferred tool called by name has no declared schema. A lesson fixes it per tool
   after the fact; declaring the parameter name in the `tool_search` description of
   the `lsp_*` group, or repairing `file_path` → `file` in `RepairToolArgs` for
   those tools, would fix it before the first error.
3. **Promotion happens fast.** Each bench task is its own session, so
   `PromoteSessions = 2` was met at the second occurrence, and both lessons were
   promoted during run 2. In real use, two chats that both hit an error are just as
   common.

## Recommendation on the constants

The numbers do not call for a change of `PromoteSeen = 3`, `PromoteSessions = 2`,
or retirement at 3 failures among the last 5 hints. They do not show either that
the current values are right. The decision is the owner's.

- **`PromoteSessions = 2` is cheap to satisfy.** The weak `Read` lesson ("use the
  correct relative file path") reached `coder`'s prompt after 3 sightings in 3
  sessions of 2 near-identical tasks: written at 22:01:54, promoted at 22:03:14.
  Each bench task is its own session, so the session rule added nothing over the
  count. This is mild evidence, from one campaign, that the session condition
  barely filters; the demotion rule (`seen_in_prompt ≥ 3`, now at 2) is what will
  remove that lesson.
- **Retirement was never exercised**: every hint was followed by a working call of
  the same tool. This bench cannot test it.

Outside the constants: the writer could answer `NONE` when the lesson only
restates the error message (`Edit`) or cannot name a change of call (`Read` with a
user-given wrong path). Those are the lessons that would sit in the prompt for
nothing.

## Limits of this task set

It shows the mechanism; it cannot show a reduction. The one error the agent makes
on its own (`lsp_diagnostics` with `file_path`) showed in 3 of 12 lessons-on
sessions and 0 of 8 lessons-off sessions. The errors that occur every time
(`read-missing-*`) come from the prompt, and no lesson can avoid them. On top of
that, on run 1 and off run 1 sometimes followed the same trajectory word for word
(`read-missing-limiter`: same commands, same 916-character answer), so the arms
are not independent samples either.

omnis is being changed so that a `Bash` command that exits non-zero counts as an
error. On `ba96fa5` it did not, unless it printed nothing. After that change,
tasks built on real `kubectl`, `git` or CLI mistakes become measurable, and agents
make those on their own. This task set predates that change.

## Next bench

Build tasks on CLI errors once a non-zero `Bash` exit counts as an error (see
above), and take more samples per cell. Re-running only the four `lsp-diag-*`
tasks with more samples is cheap (about $1 for 3 samples per arm, fresh homes),
but their error base rate is too low to be worth it.
