# Agent lessons bench (`tasks-lessons.json`)

Measures omnis **agent lessons** (feature branch `feat/agent-lessons`, design in
omnis `docs/superpowers/specs/2026-11-20-agent-lessons-design.md`): when an
agent's tool call fails and a later call of the same tool in the same run
succeeds, the host writes a one-line lesson under
`$OMNIS_HOME/lessons/<agent>/<id>.md`. The next time the agent hits the same
error, the tool result carries the lesson as a `lesson` note. A lesson seen 3
times across 2 sessions goes into the agent's system prompt. A hint that does
not help is retired. `OMNIS_LESSONS=false` turns it off.

The question: on the **second** run of the same tasks against the same
`OMNIS_HOME`, does the agent make fewer tool errors and calls, at equal
correctness? And does the lessons-off arm stay flat?

## Tasks

Six Coding-squad tasks on four small Go fixtures. Each was meant to provoke a
tool error that the agent then fixes **with the same tool**: no recovery through
the same tool means no episode, so no lesson. All run in a fresh git-seeded copy
of the fixture, so nothing outside the copy is touched.

Observed rates are from the first campaign (omnis `ba96fa5`, every agent on
`balanced`, 5 sessions per task: lessons on ×3 runs, off ×2), plus the probe
passes. They are what happened, not what the tasks guarantee.

| id | fixture | error hoped for | observed |
|---|---|---|---|
| `lsp-diag-timeout` | `timeout-go` | `lsp_diagnostics` with `file_path` | that error 0/5; instead an `Edit` whose one-line `old_string` appears twice in 3/5, a `todo_write` schema error in 1/5 |
| `lsp-diag-worker` | `worker-go` | same | 2/5 (on runs 1 and 2; off 0/2) |
| `lsp-diag-svc` | `svc-go` | same | 0/5, no tool error at all |
| `lsp-diag-limiter` | `gateway-go` | same | 1/5 (on run 1); off 2/2 failed a `Read` of an invented absolute path instead |
| `read-missing-limiter` | `gateway-go` | `Read`: the prompt names `limiter/rate.go`, the file is `internal/limiter/rate.go` | an error 5/5, caused by the prompt; the failing tool was `Bash` (a silent `find`) in 2/5 |
| `read-missing-svc` | `svc-go` | `Read`: the prompt names `cmd/server.go`, the file is `server.go` | `Read` error 5/5, caused by the prompt |

So the `lsp_diagnostics` error showed in 3 of 12 lessons-on sessions and 0 of 8
lessons-off sessions. It is the agent's own mistake: `lsp_*` tools are deferred on
`coder`, and when it calls one by name without `tool_search` it has no schema and
uses `file_path` like the fs tools. The `Read` errors are certain, but they come
from the prompt and no lesson can prevent them.

Each task's `check` list is what `correct` means:

- `{"file": f, "match": re}`: a file of the task's copy matches (the edit was made);
- `{"tool": name}`: a recorded call of that tool **succeeded** (all `lsp-diag-*`:
  the diagnostics really ran);
- `{"answer": re}`: the final answer matches. `read-missing-*` require a fact found
  only in the fixture (`b.last`, the timestamp field of the bucket; `/etc/svc.yaml`).

The checks were tightened after the first campaign; re-scoring its records
changed no result. The tasks carry no `expect`.

Tried in the probe passes and dropped, because `balanced` made no error on them:
`Edit` with a duplicated line as the only change (it Reads the file and gives a
unique block), `Edit` with a space-indented block quoted in the prompt (it Reads
the file first), `Grep` for `parseConfig(` and `*args` (it escapes the regex),
`lsp_references` / `lsp_document_symbols` (it called `tool_search` first, so it
had the schema), `Glob` limited to a directory (it puts the directory in the
pattern).

**Fixtures live in `reports/agent-lessons-2026-11-20/fixtures/`**, next to the
runner, not in `squad-bench/fixtures/`: the first campaign could only add files
in a few places. `bench.py`'s `fixture:` cwd copies only flat directories, and
`gateway-go` has a subdirectory. So the tasks' `cwd` is
`${LESSONS_FIXTURES}/<fixture>` and the runner passes a fresh copy with `--cwd`.
Running `bench.py --tasks tasks-lessons.json` directly needs `LESSONS_FIXTURES`
set, and then edits the fixtures in place. Use the runner.

## Limits of this task set

- It shows the **mechanism**: episodes are detected, lessons written, hints
  delivered on the matching error, counters updated, lessons promoted.
- It **cannot show a reduction** of errors or calls. The one error the agent makes
  on its own has a low, unstable base rate (3/12 and 0/8 sessions). The certain
  errors come from the prompt, so a lesson cannot avoid them.
- One sample per task and run.

**Next step.** omnis is being changed so that a `Bash` command that exits non-zero
counts as an error. On `ba96fa5` it did not, unless it printed nothing: a failed
`kubectl`, `git` or CLI call with an error message never produced a lesson. After
that change, tasks built on real CLI mistakes (wrong flag, missing namespace,
wrong subcommand) become measurable, and agents make those on their own. This
task set predates that change.

## What counts as a tool error

`bench.py` counts sub-agent errors only. The runner reads the session's
conversation file (`<home>/logs/conversation_<sid>.json`, kept with `--keep`).
Every tool call of the turn is recorded there with its result, root calls and
sub-agent children. The runner applies a port of omnis's own rule
(`classifyToolFailure`): a tool error, a result map with a non-empty `error`, a
result string starting with `Error` or `error `, or a hook block. The `lesson`
note is removed first, as omnis classifies before adding it. Permission, budget
and auto-mode refusals do not count. A result carrying a `lesson` key is a
delivered hint.

On `ba96fa5` this means `run_tests` failures (`run_tests: …`) and a `Bash`
command that exits non-zero with output are not errors. `Bash` with no output
(`Error: exit status 1`) is one.

## Prerequisites

- `go` (`setup-ab.sh` builds the server from a git ref of the omnis checkout).
- `gopls` on the `PATH` the server inherits (`lsp_diagnostics` uses it).
- `omnis-benches/.env` with the gateway credentials (`OPENAI_BASE_URL`,
  `OPENAI_API_KEY`), loaded with `set -a; . ./.env; set +a`.
- `git`, Python 3.

## Run

```bash
set -a; . ./.env; set +a
export MODEL=ref:balanced
W=/tmp/lessons-bench
R=reports/agent-lessons-2026-11-20/run_lessons.py
squad-bench/setup-ab.sh $W on  ba96fa5 18311                      # lessons on (default)
OMNIS_LESSONS=false squad-bench/setup-ab.sh $W off ba96fa5 18312  # setup-ab starts the server with env, which keeps it
for run in 1 2; do   # same server, same OMNIS_HOME: run 2 sees run 1's lessons
  python3 $R --server http://127.0.0.1:18311 --home $W/on/home  --arm on  --run $run --out runs-on.jsonl
  sleep 20
  python3 $R --server http://127.0.0.1:18312 --home $W/off/home --arm off --run $run --out runs-off.jsonl
done
# results.json + the report tables, offline (no model call)
python3 $R --merge runs-off.jsonl runs-on.jsonl --home-map on=$W/on/home off=$W/off/home \
    --results results.json > tables.md
# no-regression check
python3 squad-bench/bench.py --server http://127.0.0.1:18311 --token bench --tasks squad-bench/tasks-prompt-ab.json --suite --json --out promptab-on.jsonl
python3 squad-bench/bench.py --server http://127.0.0.1:18312 --token bench --tasks squad-bench/tasks-prompt-ab.json --suite --json --out promptab-off.jsonl
squad-bench/setup-ab.sh $W on stop; squad-bench/setup-ab.sh $W off stop
git -C ../omnis worktree remove --force $W/on/src; git -C ../omnis worktree remove --force $W/off/src
```

Leave ~20 s between two runs of the on arm: lessons are written by an
asynchronous worker after the turn, one model call each. Do not restart an arm
between run 1 and run 2: `setup-ab.sh` wipes the arm's home on every start,
lessons included.

After each run the runner writes a snapshot of `<home>/lessons/` next to its
`--out` file: `runs-on-lessons-on-run<n>.json`. It holds each lesson's text, state
and counters (`seen`, `hinted`, `recovered`, `repeated`). `--merge` re-reads the
conversation files, so keep the arms' homes until it has run. The first
campaign's files are in `reports/agent-lessons-2026-11-20/` with these names. Its
report is `reports/agent-lessons-2026-11-20.md`.
