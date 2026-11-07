# omnis under Harbor — reviewer A/B and regression passes (2026-11-07)

Follows [`harbor-omnis-smoke-2026-11-07.md`](harbor-omnis-smoke-2026-11-07.md).
Same setup: Harbor 0.24.0, model `deepseek-v4.1-flash-scaleway` for every agent,
the leaderboard's **smoke** subsets (3 tasks), **1 attempt** per task. omnis built
from branch-less snapshots of the working tree (`git commit-tree`):

| Snapshot | Contents (cumulative) |
|---|---|
| `a36b705` | P1 file tools, P2 compaction, P3 deferred tools, read-only agents (Landlock), skill discovery from the prompt, non-interactive AskUserQuestion |
| `6e1b77c` | + `code_docs` without the Skill group, `max_tool_calls_per_call: 20` |
| `c6145d3` | + short resume handles, per-turn time limit, review sized to the change |

## Terminal-Bench 2.1, full variant

| Pass | Resolved | Cost | Reviews | Notes |
|---|---|---|---|---|
| first smoke (`de28be5`) | 3/3 | $3.42 | 4 | |
| `a36b705` | 1/3 | $3.57 | 1 | configure-git: set up user `ubuntu`, verifier pushes as `user` (model misread, none of the changes involved). rstan: `code_docs` loaded `deep-research` for one API question, 92 web calls, 228k context, 16 min → timeout |
| `6e1b77c` | 3/3 | $3.41 | 4 | 2 timeouts (verifier passed); reviews took 65 % of portfolio's wall time |
| `c6145d3` | **3/3** | **$0.98** | 0 | coder skipped reviews (setup tasks verified by running them); configure-git 163 s (was 920 s), portfolio 257 s (was 1950 s) |

Lean stayed 3/3 (~$0.75) on `a36b705`.

## DeepSWE v1.1 — reviewer A/B on `c6145d3`

`full-noreview` = `full` minus the reviewer (dropped from the Coding squad, its
paragraph cut from the coder instruction). Both arms ran concurrently.

| Task | full | full-noreview |
|---|---|---|
| eicrud | F2P 0/14, $3.35, 2127 s | F2P 0/14, $4.78, 4233 s |
| httpx | F2P 107/108, $4.92, 3233 s (2 reviews, 2nd resumed with `"last"`) | F2P 107/108, $0.91, 725 s |
| tengo | F2P 0/91, $1.53, 1625 s (no review requested) | F2P 0/91, $1.52, 1832 s |
| **total** | **0/3, $9.81** | **0/3, $7.21** |

* **Identical test outcomes on all three tasks.** The reviewer cost +$2.60 here
  and, on httpx, 4.5× the wall time for the same 107/108.
* **The one win attributed to the reviewer (tengo, first smoke) is confounded.**
  3 of the 4 latest tengo attempts **stopped half-way, uncommitted**: two replies
  cut at the 32,000-token output limit, one where the model wrote a
  context-compaction summary (`<analysis>… <summary>… </summary>`, a format from
  other harnesses) instead of its next tool call — ADK reads either as the final
  answer. In the first smoke, each review result handed control back to the coder
  and kept it working; that, more than the review itself, may be what finished
  tengo.
* Fixed in omnis since (not in `c6145d3`): an unattended CLI one-shot whose turn
  ends that way is continued (≤ 2 times), and the time note now reaches the
  one-shot path.

## Verdict on the reviewer (provisional)

No measurable value in this sample, at a clear cost in money and wall time. Too
small to conclude (3 tasks × 1 attempt, and the decisive task is dominated by a
model failure mode). A fair re-measure needs a snapshot with the auto-continue,
both arms, ideally several attempts.

## Other observations

* The Landlock sandbox works inside the Harbor containers (checked in Docker, as
  root): reviewer probes ran in `/tmp/review-copy`, no project write.
* Skill-discovery calls: 11 in the first smoke, 0 since.
* `tool_search` never needed (no LSP use on these tasks).
* Giving omnis the task's time limit (`OMNIS_TURN_MAX_SECONDS`, from
  `task.toml`) is an omnis harness feature; other harnesses on the board do not get
  it — state it when comparing.
