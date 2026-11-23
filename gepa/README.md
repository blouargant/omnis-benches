# gepa — evolve omnis agent texts with GEPA

Runs [GEPA](https://github.com/gepa-ai/gepa) ("reflective prompt evolution")
on the texts an omnis agent runs on, scored by the scripted squad-bench
suites. Design: `../omnis/docs/superpowers/specs/2026-11-23-gepa-prompt-evolution-design.md`;
plan: `docs/superpowers/plans/2026-11-23-gepa-optimizer.md`.

## What it does

1. Reads the seed texts from the omnis checkout (`omnis_src`, default `../omnis`).
2. Starts `workers` bench servers (`squad-bench/setup-ab.sh`, `MODEL=tiered`),
   each with its own `fake_subagents.py`: the leader runs on the search model,
   its sub-agents are scripted.
3. GEPA evaluates candidates on the `train` and `val` tasks of `suites.json`:
   each candidate is written into the servers' user layer and hot-reloaded (a
   reload that does not take stops the run). Proposals come from the reflection
   model (`premium`) and are refused when they drop a rule of `keep/`, name a
   scenario detail, or grow past +30 % of the seed.
4. Stops at `max_metric_calls` or at `search_share` (default half) of `ceiling_usd`,
   whichever first; the rest is kept for the held-out check, which aborts if it
   reaches the ceiling. A task that fails twice for infrastructure reasons
   (bench, gateway, fake server) stops the run: fix and resume.
5. Runs the seed and the best candidate on the **held-out** tasks, on every
   model of the run (`repeat_heldout` times) — scripted tasks on fake
   sub-agents, the others (e.g. `tasks-leader-real.json`) on the real squad — and decides: adopt when no
   (agent, model) falls below the seed's 90 % bootstrap interval and one
   rises above it.
6. Writes `reports/gepa-<name>-<date>.md` and `gepa/out/<name>/best.patch`.
   **Nothing is applied to omnis**: review the patch and commit it by hand.

## Components

| Name | Text |
|---|---|
| `instruction:<agent>` | `registry/agents/<agent>/instruction.md` |
| `turn_reminder:<agent>` | `turn_reminder` of that agent's `agent.json` |
| `skill:<name>` | body of `registry/skills/<name>/SKILL.md` |
| `prompt:<id>` | refused until omnis has `prompt_overrides.json` (spec part 1) |

Every agent a component reaches needs an entry in `suites.json` with a
held-out set (or be listed in the run's `heldout_ok_missing`); otherwise the
run refuses to start.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r gepa/requirements.txt pytest
set -a; . ./.env; set +a
.venv/bin/python gepa/optimize.py denylist  gepa/runs/leader-system.json   # what proposals may not say
.venv/bin/python gepa/optimize.py calibrate gepa/runs/leader-system.json   # cost per evaluation
.venv/bin/python gepa/optimize.py run       gepa/runs/leader-system.json   # resumable: same command
```

`gepa/out/<name>/` holds the GEPA checkpoints, `ledger.jsonl` (dollars, kept
across a resume), `records.jsonl` (every bench record), `proposals.jsonl` (every
proposal and why it was refused), `run.log`, `best.json`, `best.patch`.

Tests: `.venv/bin/python -m pytest gepa -q` (no network).
