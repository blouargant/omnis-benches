# Agent lessons: is there a gain? (2026-11-20)

**Answer: not a measurable one.** On tasks built to favour the feature, lessons
changed nothing on the production models and gave small, non-significant
trends on the cheap model. Two causes were found, and one of them is a design
limit of the feature, not a tuning problem.

## What was run

- **Fixture** (`agent-lessons-gain-2026-11-20/fixtures/acme`): a small shell
  project with four traps a model cannot guess.
  - *Explicit* (the error says what to do): `./bin/acme build` needs
    `--profile`; `./scripts/migrate.sh status` needs `--db`.
  - *Opaque* (the error is a code, the fix is in `docs/`): `make test` fails
    with `E17` until `make bootstrap`; `./bin/acme release notes` fails with
    `E42` until `--since-tag`.
- **Tasks** (`squad-bench/tasks-lessons-gain.json`): each trap is met in five
  different sessions (a different small side task each time), plus five control
  tasks with no trap: 25 sessions, in round-robin order. Every session gets a
  fresh copy of the fixture, so the trap is there again; only omnis's home (the
  lessons) carries over. Trap tasks end with "If a command fails, work out why
  and get it to succeed", the same in both arms.
- **Arms**: lessons on, lessons off (`OMNIS_LESSONS=false`), five repetitions
  each, every repetition on its own server and empty home. Coding squad.
- **Measured per session**, independently of omnis's own error
  classification: trap hits (Bash results carrying the trap's error text), tool
  calls, model calls, prompt tokens, cost, wall time, hints delivered, correct.
- **Three runs, 750 sessions, $13.75**:
  - `balanced` on every agent, omnis as merged (`7f2b520`);
  - `balanced`, omnis with the tool-key fix below (`0a531e0`);
  - production tiers (`coder` on `premium`), with the fix.
- This is the **best case** for the feature: the same environment-specific
  error, met again and again by the same agent. The earlier report
  (`agent-lessons-2026-11-20.md`) is the neutral case.

Sessions with no model call or an empty answer (the gateway returned nothing,
with ten servers in parallel) are excluded and counted: 34 of 500 on
`balanced`, 0 of 250 on the production tiers.

## Results

Exposures 2 to 5 of the trap tasks (exposure 1 cannot differ: no lesson exists
yet). Mean per session; p from a permutation test on per-repetition means.

| Model | Metric | Lessons off | Lessons on | Change | p |
|---|---|---|---|---|---|
| balanced, as merged | Trap hits | 0.68 | 0.62 | −8 % | 0.50 |
| | Tool calls | 7.32 | 6.93 | −5 % | 0.44 |
| | Cost $ | 0.0188 | 0.0181 | −4 % | 0.44 |
| balanced, with the fix | Trap hits | 0.68 | 0.61 | −9 % | 0.37 |
| | Tool calls | 7.32 | 6.74 | −8 % | 0.14 |
| | Cost $ | 0.0188 | 0.0180 | −5 % | 0.26 |
| production tiers, with the fix | Trap hits | 0.74 | 0.68 | −8 % | 0.12 |
| | Tool calls | 3.61 | 3.64 | +1 % | 0.89 |
| | Cost $ | 0.0239 | 0.0249 | +4 % | 0.36 |

The `balanced` baseline pools the lessons-off repetitions of both runs (10).
Correct answers do not differ: 151/154 off, 77/78 and 71/73 on (`balanced`);
80/80 in both arms (production tiers). Control tasks do not differ either.
Full tables: `tables-balanced.md`, `tables-tiered.md`, `tables-recovery.md`.

No difference reaches significance. Five repetitions per arm cannot rule out
a small effect; they do rule out a large one.

## Why there is no gain

**1. Models recover by themselves, cheaply.** Tool calls between the first
failing result and the first successful one:

| Model | Trap kind | No hint | With a hint |
|---|---|---|---|
| balanced | explicit | 1.0 – 1.2 | 1.0 – 1.3 |
| balanced | opaque | 2.6 – 2.8 | 1.7 – 2.2 |
| production tiers | explicit | 1.2 | (no hint was ever delivered) |
| production tiers | opaque | 1.2 | (no hint was ever delivered) |

A hint saves nothing on an explicit error and less than one call on an opaque
one, for the cheap model. `premium` reads the docs and fixes an opaque error in
1.2 calls on its own: there is nothing left to save.

**2. A lesson in the prompt does not prevent the error.** On `balanced`, with
two to three lessons promoted into `coder`'s prompt by exposure 5, trap hits
at exposure 5 are 0.65–0.80 per session, against 0.78 without lessons. The
model runs the command as asked, fails, then applies the fix.

**3. On the production model the mechanism does not engage at all.** In 100
trap sessions with lessons on, 68 hit a trap and **no hint was delivered**;
lessons stayed at `seen: 1` and the same error got several lessons. `premium`
writes compound commands: 79 % of its Bash calls chain several commands
(`sed -i …; head -1 README.md; make test 2>&1 | tail -30`,
`./scripts/migrate.sh status; echo "exit=$?"; ls`), against 37 % for
`balanced`. The feature assumes one Bash call is one command:

- the tool key is the first word of the call (`sed`, `echo`, `cat`), so the
  failure and the later success have different keys and no episode forms;
- the exit status is the last command's, so `…; echo "exit=$?"` is a success;
- the error text holds the other commands' output, so the signature changes
  every time.

This is a limit of the design. The host sees one exit status and one output
per Bash call; it cannot tell which command of a chain failed.

## A defect found and fixed on the way

On `balanced`, a command prefixed with `cd <dir> &&` was keyed `Bash:cd`, so
the same mistake typed with and without the prefix had two signatures: hints
reached 16 of 42 opaque-trap hits and the same error was learned twice (5 to
11 lessons per repetition). With the fix (omnis branch
`fix/lessons-toolkey-cd`, commit `0a531e0`: a leading `cd`/`pushd` is skipped)
hints reached 28 of 40 and repetitions ended with 3 to 6 lessons. The fix does
what it should; it does not change the conclusion.

## What was not tested

- Errors whose recovery is **expensive**: a command that runs for minutes
  before failing, a fix that takes many steps to find. The saving per avoided
  error would be larger there. None of the four traps is of that kind.
- Non-Bash tool errors. Lessons were written for some during these runs
  (`Read` with an absolute path that does not exist, `memory_save` argument
  errors, an unsupported `workingDirectory` argument to Bash) and their hints
  were followed by a working call, but the bench does not measure them.
- Long sessions. Every session here is one short turn.

## Side effects observed

- No harm: correctness and the control tasks are unchanged in every run.
- Lessons-on costs one extra model call (the writer, on the evaluator model)
  per new lesson; it is not in the session costs above. 3 to 11 per repetition
  of 25 sessions.
- Lesson quality is uneven. Good: "Run make bootstrap before make test to
  initialize the workspace." Poor: "When encountering a non-descriptive error
  like E42, append diagnostic commands…" (it recorded a diagnostic command as
  the arguments that worked).

## Reading

As built, agent lessons do not pay for themselves on these tasks: no effect on
the model that runs the Coding squad in production, and a few percent at most,
unproven, on the cheap one. The two things that could change that are outside
what was measured: errors that are costly to recover from, and a way to
attribute a failure inside a compound Bash command.

## Reproduce

```
cd reports/agent-lessons-gain-2026-11-20
python3 gen_tasks.py                                  # writes squad-bench/tasks-lessons-gain.json
./run_all.sh /tmp/gain-bal ref:balanced 5 18500       # needs ../../.env (gateway), go, an omnis checkout at ../../../omnis
./run_all.sh /tmp/gain-tier tiered 5 18560
python3 analyze.py "on=/tmp/gain-bal/runs.jsonl"
python3 recovery.py /tmp/gain-bal                     # needs the arms' homes
```

`data/` holds the records of the three runs and the lessons each lessons-on
repetition ended with.
