# session-study — do scenarios from real sessions find what our tasks miss?

A study tool, not a bench that runs forever. It reads the conversation files of
an omnis install, finds the turns that went wrong, has a person confirm them,
rewrites the confirmed ones as squad-bench scenarios, replays those, and writes
a report with a verdict decided by a rule fixed in advance.

Design: `../omnis/docs/superpowers/specs/2026-11-25-session-scenarios-study-design.md`.
Background: Perplexity's "Self-improving skills" (2026-11-18) builds its skill
tests from real failed sessions; this measures whether that is worth doing for
omnis before anything is added to omnis.

**`out/` holds session text. It is git-ignored and must never be committed.**
The only committed file with scenario text is `tasks-sessions.json`, and only
scenarios that were read and passed `check` go in it.

## The steps

```bash
set -a; . ./.env; set +a                    # gateway for the judges
python3 session-study/study.py scan          # 1. read sessions, compute signals   -> out/turns.jsonl
python3 session-study/study.py judge         # 2. one model verdict per turn       -> out/judged.jsonl
python3 session-study/study.py review        # 3. cards to read                    -> out/review.md, out/verdicts.json
#    fill out/verdicts.json: failure = yes / no / unsure, kind, note
python3 session-study/study.py draft         # 4. a scenario per "yes", 2 controls -> out/scenarios-draft.json
python3 session-study/study.py check         #    session text left in the drafts?
python3 session-study/study.py check --allow Qwen,vLLM --accept ss-1,ss-c1
python3 session-study/study.py replay --server http://127.0.0.1:<port> --token bench   # 5.
#    write out/coverage.json (below)
python3 session-study/study.py report        # 6. -> reports/session-scenarios-knowledge-<date>.md
```

Every step reads and writes files under `out/`, so one step can be re-run
alone. `judge`, `draft` and `replay` call models; the others do not.

- **`scan`** — default logs directory `$OMNIS_HOME/logs`, else `~/.omnis/logs`
  (`--logs`). Hidden sessions are skipped. Signals: `tool_error`, `blocked`,
  `halted`, `empty_subagent`, `repeated_call` (same call 3 times), `many_calls`
  (above the squad's 90th percentile), `reply_cut`, `empty_reply`,
  `user_pushback`.
- **`judge`** — every turn with tool calls, flagged or not, so that what the
  signals miss is measured. A turn whose verdict failed to parse is retried on
  the next run; the others are kept.
- **`review`** — one card per flagged turn plus 8 turns nobody flagged, shuffled.
  A card does not say why it was picked. Once `verdicts.json` exists the cards
  are frozen: a later `judge` run does not renumber them.
- **`draft` / `check`** — the model rewrites the task with invented names. `check`
  lists what is left of the source turn in each draft (names, paths, hosts,
  e-mail addresses, numbers of 4 digits or more) and exits 1 when there is any.
  A public product's name that the task is about is allowed by hand with
  `--allow` (kept in `out/allowed.json`, printed at every check). `--accept`
  refuses a draft that still leaks.
- **`replay`** — needs a running omnis-server on production tiering, e.g.
  `MODEL=tiered squad-bench/setup-ab.sh <workdir> study worktree <port>`. Each
  scenario runs 5 times (`--repeat`) through `squad-bench/bench.py`; each run is
  judged against the scenario's rubric by `--judge-model` (default `gpt-5.5`,
  another family than the leader's). Stops starting runs at `--ceiling` dollars
  (default 30). Resumable.
- **`report`** — needs `out/coverage.json`, written by hand, one entry per
  scenario that reproduces:

  ```json
  {"ss-1": {"covered_by": "", "group": "search loop", "missing_signals": ["a Stop by the user"]}}
  ```

  `covered_by` names an existing tasks file that already exercises the
  behaviour (empty when none); scenarios sharing a `group` count as one
  failure; `missing_signals` is optional.

## How a scenario is counted

- A run that timed out, was cancelled, ended on a question, or returned nothing
  is **invalid**: it is never a failure seen.
- A failure **reproduces** when the scenario's specific failure is seen in at
  least 2 of 5 runs. More than 2 invalid runs, or fewer than 3 valid ones
  without 2 failures: **not measured**.
- A control scenario must pass in at least 4 of 5 runs; a failing control puts
  a warning above the verdict.
- Verdict: **go** at 3 or more distinct failures that reproduce and that no
  existing suite covers, **stop** at 0, **undecided** at 1 or 2.

Tests (no network): `python3 -m unittest discover -s session-study`.
