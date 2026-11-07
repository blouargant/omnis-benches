# omnis under Harbor — first smoke run (2026-11-06/07)

Adapter: [`harbor/`](../harbor/README.md). Per-trial data:
[`harbor-omnis-smoke-2026-11-07.jsonl`](harbor-omnis-smoke-2026-11-07.jsonl).

**Setup.** Harbor 0.24.0, local docker. The leaderboard's **smoke** subsets
(3 tasks each), **1 attempt** per task. Model `deepseek-v4.1-flash-scaleway`
on the ChapsVision gateway, for every agent (single-model override). Prices
0.63 / 1.89 / 0.126 $/M (input / output / cached input). omnis `develop` @
`de28be5` (2 TB-lean trials ran on `3d4ed6b`, the branch tip that was merged
as `de28be5`: same code). Variants: `full` = the shipped Coding squad,
`lean` = `coder` alone with `fs` + `tests`.

## Results

| Bench | Variant | Resolved | Cost | $/trial | Prompt tok (cached) | Model calls | Agent time |
|---|---|---|---|---|---|---|---|
| TB 2.1 | lean | **3/3** | $0.82 | 0.27 | 2.2M (70 %) | 116 | 34 min |
| TB 2.1 | full | **3/3** | $3.42 | 1.14 | 12.5M (84 %) | 339 | 75 min |
| DeepSWE | lean | 0/3 | $3.88 | 1.29 | 14.7M (85 %) | 228 | 75 min |
| DeepSWE | full | **1/3** | $29.38 | 9.79 | 135.4M (90 %) | 1359 | 6.2 h |

Per task:

| Task | lean | full |
|---|---|---|
| tb/configure-git-webserver | ✔ $0.18 | ✔ $0.61 |
| tb/portfolio-optimization | ✔ $0.28 | ✔ $2.29 |
| tb/rstan-to-pystan | ✔ $0.35 | ✔ $0.52 (agent timed out at 1800 s, verifier passed) |
| deepswe/eicrud-keyset-pagination-cursor | ✘ F2P 0/14, $2.11 | ✘ F2P 0/14, $8.91 |
| deepswe/httpx-streaming-json-iteration | ✘ F2P 106/108, $0.94 | ✘ F2P 104/108, $6.66 |
| deepswe/tengo-destructuring-bindings | ✘ F2P 0/91, $0.83 | ✔ F2P 91/91, $13.81 |

(F2P = the task's fail-to-pass tests; resolve needs all of them plus every
pass-to-pass test.)

## What it says

* **The adapter works end to end** on both benchmarks: install, run, verifier,
  token/cost accounting, DeepSWE offline agent phase with only the gateway
  allow-listed (no infra error in the 12 trials).
* **On TB, `full` costs 4.2× `lean` for the same 3/3.** The extra spend is the
  ~16k-token fixed prompt (vs ~4.7k) re-sent on every call, plus the `reviewer`
  loop; `code_scout`, LSP and ast-grep were never used.
* **On DeepSWE, `full` is 7.6× the cost and wins one task (tengo).** Its driver
  is the `reviewer` sub-agent: 521 of 1359 calls, and the coder → reviewer →
  fix loop that made trials run 1.7–2.4 h (the task timeout is 3 h). Lean's
  tengo attempt stopped after 31 calls with no F2P test passing — `full`'s
  review loop is what got that one over the line. httpx is near-miss in both
  (2 and 4 F2P failures); eicrud fails identically in both (0/14, and the same
  10 P2P failures), which looks like a task-level difficulty, not a variant
  effect.
* **No pinned answer yet on "does the team pay for itself".** One attempt × 3
  tasks cannot separate the variants on resolve rate; only the cost ratio is
  solid (consistent across 6 task pairs).

## Limits — read before comparing with the board

* **3 tasks, 1 attempt.** Not a score. The board runs 3 attempts × 87 (TB) /
  111 (DeepSWE) tasks.
* **Different model route** (gateway → Scaleway, not the HF router provider the
  board pins), **reasoning effort not pinned**, **cost from omnis's own event
  log** and configured prices, **no atif-scan**. Absolute numbers are
  indicative; the `full` vs `lean` comparison is like-for-like.
* **Cache share is high** (70–90 % of prompt tokens served from the provider's
  prompt cache); the cost model credits it at 0.126 $/M. A provider without
  prompt caching would make `full` relatively more expensive still.
* **Interactive question in a non-interactive run.** In the `full` eicrud trial
  the coder asked the user how to branch (no `main` branch in the repo); stdin
  is at EOF so the question was cancelled and the agent went on. Harmless here,
  but a prompt reminding the agent it runs unattended would avoid a wasted
  call — a candidate omnis follow-up (a bench-mode instruction or using
  `OMNIS_NON_INTERACTIVE` to refuse `ask_user` with a clear message).
* Local deviations: the DeepSWE egress sidecar was built without buildx
  (`prebuild-sidecar.sh`, same image minus a BuildKit-only `COPY` flag);
  Kubernetes hook, curator/reflector and turn budget disabled.

## Cost of the full campaign (extrapolated, not run)

At these per-trial means, 3 attempts × full subsets: TB lean ≈ $71, TB full
≈ $300, DeepSWE lean ≈ $430, DeepSWE full ≈ $3 300 — about **$4 100** and
several days of wall time at concurrency 4 (DeepSWE full averages 2 h/trial).
The `pilot` subsets (50 tasks each) cost roughly half. Not launched — needs a
go-ahead.
