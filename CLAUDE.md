# CLAUDE.md — omnis-benches

Guidance for Claude Code (claude.ai/code) working in this repo. This is the
**evaluation / benchmarking** companion to [omnis](https://github.com/blouargant/omnis)
(cloned next to it at `../omnis`).

## What this repo is (and the golden rules)

- **All omnis benchmark/eval tooling lives here — never in the omnis repo.** The
  omnis CLAUDE.md makes this a hard policy. When asked to add or change a bench,
  do it here.
- **Dependency-free: Python stdlib only.** No pip installs, no third-party
  packages. Match the existing style (`urllib.request` for HTTP, `argparse`,
  `subprocess`). If you reach for a dependency, stop and reconsider.
- **Nothing imports omnis.** These tools drive omnis (or a raw model endpoint)
  **over HTTP / as a subprocess**, so the repo evolves independently of omnis's Go
  code. Do not add a Go-module dependency on omnis.
- **Model credentials come from the environment** (whatever the omnis
  `models.json` reads, e.g. `OPENAI_BASE_URL` / `OPENAI_API_KEY`). Tools never
  hold secrets. **Single mechanism — a project-root `.env`:** put those vars in
  `omnis-benches/.env` (gitignored; never commit it). `k8s-ai-bench/run.sh`
  sources it automatically with auto-export (`set -a; . "$ROOT/.env"; set +a`), so
  the values reach the omnis-server it spawns. For the Python benches, `source .env`
  (or the `set -a … set +a` form) before running. **Every new bench or test MUST
  use this same root-`.env` mechanism** — never hardcode endpoints/keys or invent
  per-tool credential loading. (`source ../omnis/.env` still works if you have the
  omnis checkout next door, but the root `.env` is the canonical path in this repo.)

## Self-maintenance

After any change to a tool's interface, metrics, flags, or a new bench, update
this file and the affected tool's README so they stay the single source of truth.
Keep the "Gotchas" section current — it encodes hard-won facts.

## Layout

| Dir | What it is | Entry point |
|---|---|---|
| `squad-bench/` | **Squad-behaviour** benchmark: drives a running omnis-server like the web UI (session pinned to a squad → one task → stream the SSE) → a metrics record. Swap an agent's model/instruction, re-run the same task, compare. | `bench.py` |
| `squad-bench/campaign.py` | **Interleaved multi-variant campaigns** over `bench.py` + `variants.py`: alternates config variants in time against the same task suite with a V0 drift witness, flags search-backend degradation post-hoc, and reports medians with their observed spread. | `campaign.py` |
| `model-probe/` | **Endpoint capability** probe: verifies a live OpenAI-compatible endpoint+model supports the features omnis uses (streamed chat, tool calling streaming+non-streaming, parameterless tools over streaming, tool-result round-trip, caching/usage/model-info). Exit≠0 iff a critical check fails. Has its own **`model-probe/CLAUDE.md`**. | `probe.py` |
| `k8s-ai-bench/` | Adapter for the gke-labs **k8s-ai-bench** suite (Pass@k on real k8s tasks against ephemeral clusters), so omnis is scored comparably to other agents. | `omnis-agent` |

`model-probe` tests a *raw endpoint*; `squad-bench` tests *squad behaviour* once
that endpoint is wired into omnis. Sister tools.

## How omnis is driven (the HTTP rail)

Both `squad-bench/bench.py` and `k8s-ai-bench/omnis-agent` drive a **running
omnis-server** the same way the web UI does:

1. `POST /api/sessions {squad, dir, name}` → a session pinned to a squad.
2. `POST /api/sessions/:id/messages {prompt}` → stream the **SSE** (events:
   `token`/`message` = assistant text, `tool_call`/`agent_tool_call` = tool
   activity, `turn_usage` = per-agent model cost, `ask_user`, `done`). Frames
   carry an `id:` seq; reconnect via
   `GET /api/sessions/:id/messages/stream?from=<seq>` (204 = finished).
3. `POST /api/sessions/:id/cancel` to stop; `DELETE /api/sessions/:id` to clean up.

The SSE parser + session driver are duplicated (small, self-contained) in both
tools — keep them in sync if you change the protocol handling.

## squad-bench

- `python3 squad-bench/bench.py --suite | --task <id> [--repeat N] [--out f.jsonl] [--deadline s]`.
- Metrics per run: `wall_ms`/`ttfb_ms`, `token_events` (streaming granularity),
  `delegations`/`redispatches`, `leader_tools`/`subagent_tools`, per-agent
  `models` cost, `subagent_errors`, `ask_user` (want 0), `correct` (vs a task's
  `expect` substring or `/regex/`), quality_gate / facts / forbidden_hits
  (deterministic layer-1 scoring, see scoring.py), fetches / distinct_urls /
  facts_per_fetch. Tasks in `squad-bench/tasks.json`;
  `cwd:"sandbox"` tasks run against a git-isolated temp copy of
  `squad-bench/sandbox/`.
- **Tune prompts on weak models first.** A cheap model that "gets lost" is usually
  a *prompt* problem — tighten the agent's `instruction.md` (numbered procedure +
  explicit stop conditions), reload, re-run, watch redispatches/over-search drop.
- `tasks-kubernetes.json` + `README-kubernetes.md`: the k8s_editor/k8s_cleaner
  model-tier sweep (leaderless-solo-squad + models.json-override methodology).
- Multi-turn tasks: a task may declare `prompts: [...]` instead of `prompt`;
  answers land in `answers[]` and `facts` rules select a turn with `on: <index>`.
- **`est_cost_usd` billing is cache-aware — cached tokens are never double-charged.**
  `prompt_tok` follows the OpenAI usage convention and already **includes**
  `cache_read_tok` as a subset, not an addition, so `note_model` bills only the
  uncached remainder (`prompt_tok - cache_read_tok`, clamped at zero) at the full
  input price; `cache_read_tok` pays the (usually much cheaper) cache-read price;
  `out_tok` pays the output price. Billing the full `prompt_tok` **and**
  `cache_read_tok` both at their own price (the pre-fix formula) double-charges
  the cached portion — verified regression: an 84%-cache-hit agent
  (182311 prompt / 153089 cache-read / 3052 output) read **$0.668** instead of
  the correct **$0.186**. Any JSONL record captured **before** this fix carries
  an inflated `est_cost_usd`/`total_cost_usd` for an agent with non-zero
  `cache_read_tok` (zero-cache agents, e.g. every `web_agent` record, are
  unaffected); it can be recomputed from the record's own retained
  `prompt_tok`/`cache_read_tok`/`out_tok` (plus the `cache_read_price_per_m`
  from the `models.json` active when it was captured, since the record doesn't
  persist that price per agent). Do not compare a pre-fix and post-fix record
  for a caching agent as if they were on the same scale.
- `campaign.py` — interleaved multi-variant campaigns with a V0 drift witness;
  `variants.py`/`variants.json` apply config variants over the HTTP API (verified
  apply, checked revert). Several things beyond the base campaign loop:
  - **`drift_ok` compares the opening/closing witness PER TASK, never pooled
    through one median.** Pooling is blind exactly where it matters:
    `web-deep-ds7` declares only *optional* facts (a regex checklist can't
    judge free-form research prose, so its layer-1 gate is deliberately
    non-gating), so its `quality_gate` is unconditionally `True` and a pooled
    True/False check could never see it degrade; and with exactly 3 witness
    records, a pooled cost median picks the middle-ranked value, immune to a
    blow-up in whichever single record is already the outlier — almost
    always the deep task. Each task is now checked against its own opening
    self on three signals: quality regression (`quality_gate` True→False,
    catches `web-lookup`/`web-canary`), **observation-count collapse**
    (`facts.optional_found` count drops to <half — catches `web-deep-ds7`,
    whose `quality_gate` can't itself fail; the >2x threshold is *measured*:
    a healthy `web-deep-ds7` run yields 5 observations, three separately
    captured degraded-search runs yielded 1/2/3), and per-task cost blow-up
    (`COST_DRIFT_FACTOR`, now applied per task instead of to a pooled
    median). `campaign.OBSERVATION_DROP_FACTOR` is the tunable.
  - **Exit codes are `0`/`2`/`3`, not `0`/`2`.** `0` = stable + revert clean;
    `2` = drift witness voided the campaign (a task's numbers regressed) but
    the revert still round-tripped; `3` = **the revert itself failed** —
    printed and exited distinctly from `2` because it means the server is
    left in a mismatched config state for whatever runs next, independent of
    whether the campaign's own results looked fine. A revert mismatch used
    to be printed but silently ignored by the exit code — fixed because a
    real campaign was queued behind this and a false "success" would have
    run it against a misconfigured server.
  - **Post-hoc search-degradation detection** (not a pre-flight probe — the
    fleet runs a paid Serper backend, so probing e.g. DuckDuckGo would measure
    the wrong thing): every completed record is inspected after the fact and
    flagged `search_degraded` (+ `degraded_reason`) when its `subagent_errors`
    carry a search-failure marker (deadline exceeded / timeout / non-functional
    / rate limit / 429 / no results, case-insensitive) or its `fetches` count
    sits >3x from the median of its same-task-and-variant peers in the
    campaign (variant-scoped so a variant that legitimately fetches fewer
    times by design, e.g. one that delegates fetching to collapse an F^2
    term, is never penalized for doing its job). Degraded
    records stay in the JSONL but are excluded from the end-of-campaign medians.
    **The fetch-count ratio test additionally requires the peer median itself
    to be ≥ `FETCH_ANOMALY_MIN_PEER_MEDIAN` (5) before it applies at all** — a
    real campaign flagged three `web-lookup` runs as `search_degraded` with
    reasons `fetches=3 vs peer median 0.5`, `fetches=0 vs peer median 1.0`, and
    `fetches=0 vs peer median 2.0`: on a task that legitimately makes 0-3
    fetches, one or two fetches of noise produces a huge ratio, and a "peer
    median" under 1 isn't a meaningful quantity to divide by. Below the floor
    the ratio test is a no-op and only the volume-independent
    `subagent_errors` marker can flag the run — a search backend failing is a
    real signal whatever the fetch count, so that half is deliberately
    unweakened. 5 was picked because every observed false-positive peer
    median (0.5, 1.0, 2.0) sits well under it while the one confirmed genuine
    anomaly on record (21 fetches vs a peer median of 108) sits two orders of
    magnitude above it — `fetches_anomalous(record, campaign_records,
    min_peer_median=...)` is the tunable if that gap ever needs narrowing.
    **GOTCHA: the fetch-count half is inert at `--repeat 2`** (the CLI default
    and the usage example) — `fetches_anomalous` needs ≥2 same-task/variant
    peers, which a non-`V0` variant only accumulates at `--repeat >= 3` (`V0`
    always has 3 via its witness-open/campaign/witness-close trio). The
    `subagent_errors`-marker half is unaffected by `--repeat`.
  - **Medians are always reported WITH their spread** (min–max range + run
    count), never as a bare number or a bare "N% cheaper" claim — two runs of
    the *identical* config were measured to differ 1.85x in cost and 1.5x in
    fetches, so a difference smaller than that spread is not evidence of
    anything. `campaign.spread()`/`campaign.campaign_summary()` are the tested
    building blocks; `print_campaign_summary` is the CLI's end-of-run report.
  - `main()`'s control flow (revert-on-raise, verify-abort, exit codes) has
    committed test coverage in `TestCampaignMain` via `_FakeSwitcher` +
    a fake `bench.run_task` — **never a live server**, so these tests are
    safe to run alongside a real campaign against the running instance.
- Unit tests: `python3 -m unittest discover -s squad-bench` (stdlib only).

## model-probe

- `python3 model-probe/probe.py -u <base> -m <model> -k <key>`; `--list` shows all
  checks. **Add a check** by dropping `model-probe/checks/<name>.py` with
  `@check(...)` functions — auto-discovered, no wiring. Full guide in
  `model-probe/CLAUDE.md`. When omnis starts depending on a new model capability,
  add a check here.

## k8s-ai-bench (adapter)

k8s-ai-bench (`../k8s-ai-bench` upstream, cloned by `run.sh`) drives an agent as a
CLI binary shaped like `kubectl-ai` (`--agent-bin`), calling it per task with
`--kubeconfig <path>` + `KUBECONFIG` in the env and the task prompt on **stdin**,
then scoring with the task's `verify.sh` on an ephemeral kind cluster.

`omnis-agent` is that binary. **Design (do not "fix" without reason):**

- **One shared server per run + auto cluster teardown (do not revert to per-task
  servers).** omnis-server multiplexes sessions, so `run.sh` (kind path) owns the
  lifecycle: it creates the shared kind cluster `k8s-ai-bench-eval`, starts ONE
  omnis-server bound to it (`KUBECONFIG=<shared>`), hands the harness
  `--cluster-creation-policy DoNotCreate --kubeconfig <shared>`, and on exit stops
  the server and **deletes the cluster** (the upstream harness never deletes it —
  it only `defer os.Remove`s the temp kubeconfig *file*). It exports
  `OMNIS_SERVER=<url>` + `OMNIS_SHARED_CONTEXT=kind-k8s-ai-bench-eval`. Each
  `omnis-agent` invocation opens a session on that server when the task's
  kubeconfig current-context matches `OMNIS_SHARED_CONTEXT`; a task that declares
  `isolation: cluster` (the whole `gatekeeper/*` suite → its own cluster) gets a
  **dedicated throwaway server** spawned by `omnis-agent`, since a shared server
  bound to one cluster can't reach a different one. Knobs: `CONCURRENCY=N`
  (default **1 = sequential**; see the concurrency gotcha), `KEEP_CLUSTER=1`,
  `SHARED_CLUSTER=<name>`; `CLUSTER_PROVIDER=vcluster` keeps the per-task-server
  path (every vcluster task is isolated). `OMNIS_SERVER=<url>` alone (no
  `OMNIS_SHARED_CONTEXT`) still drives one existing server for everything (debug).
- **Shipped squad unchanged + allow-all permissions.** `bench-permissions.json`
  (`bypassPermissions`) is copied into the per-task `OMNIS_HOME` so the
  confirmation-oriented squad mutates the sandbox without a human. Known risk: the
  squad may narrate a plan instead of fully acting → low Pass@k is an honest
  signal, not a bug.
- **Fixed omnis fleet.** `--model` / `--llm-provider` are accepted and **ignored**
  (omnis uses its own fleet); the harness's model column is a label. To vary
  omnis's models, change the omnis config.
- **Token/cost accounting.** `omnis-agent` folds `turn_usage` frames into a
  per-agent tally (prompt/output/cache-read tokens, calls, est. USD cost — same
  math as squad-bench's `models` block) and prints a summary to **stderr**
  (`omnis-agent: usage …`), also appended as a footer to `--trace-path`. Diagnostic
  only; stdout stays the answer the harness scores, so Pass@k is unaffected.
- Env: `OMNIS_SERVER_BIN` (omnis-server binary), `OMNIS_BENCH_SQUAD` (default
  `kubernetes`), `OMNIS_BENCH_DEADLINE`. Running the full suite needs
  **kind + docker + go** (not auto-installed).

## Gotchas (hard-won)

- **`OMNIS_CONFIG_DIRS` does NOT redirect the omnis agent registry** — only config
  *files*. A per-agent `model_ref` edit in a custom config dir is ignored; the
  registry resolves from the default chain (`.agents` → `$HOME/.omnis` →
  `/etc/omnis`). To swap the model for a bench, use the **single-model override**
  in `models.json` (`override_model_ref` + `override_model_enabled`,
  hot-reloadable), and **always verify the recorded per-tier price actually
  changed** (each record's `models` block carries in/out `$/M`) before trusting a
  sweep — a silent no-op swap makes every tier look identical.
- **squad-bench never answers `ask_user`.** So a tool call that raises a
  permission prompt hangs to the deadline — and, conversely, **no mutation can
  execute** (the bench can't approve it). For cluster-touching squad-bench tasks,
  gate the omnis server: hard-deny mutations + broadly allow reads (incl.
  `Bash(*)`) so nothing hangs and the cluster stays read-only. (k8s-ai-bench is
  different: it *wants* mutation, hence `bypassPermissions` + a throwaway kind
  cluster that `run.sh` deletes at the end of the run.)
- **k8s-ai-bench's task loader is FLAT** — `loadTasks` reads only top-level
  `tasks/<id>/task.yaml` and **errors on any top-level dir lacking one**. The only
  offender is `tasks/gatekeeper/` (tasks nested a level deeper), so a plain
  `./run.sh` over `tasks/` (or any pattern matching `gatekeeper`) aborts with
  `failed to read task file tasks/gatekeeper/task.yaml`. Run that suite with
  `TASKS_DIR=<clone>/tasks/gatekeeper` (a `run.sh` knob). Every gatekeeper task is
  `isolation: cluster` → its own cluster → a dedicated omnis-server (the
  shared-server fallback path; validated with `must-have-key`). **To run the 25
  main tasks in one shot**, the filter is applied *before* the file read
  (`eval.go` `loadTasks`), so `TASK_PATTERN='^[^g]'` skips the `gatekeeper/` dir
  cleanly (gatekeeper is the only top-level entry starting with `g`; RE2 has no
  negative lookahead, so this char-class trick is the simplest safe exclusion).
- **`--concurrency 0` (the harness default) means "auto = number of tasks"** —
  i.e. it runs EVERY task at once (`main.go` sets `Concurrency = len(tasks)`). On
  the shared single-cluster/single-server kind path that's wrong: parallel mutating
  tasks contend for one node and flood the model endpoint → noisy, untrustworthy
  pass/fail. `run.sh` therefore forces sequential via `CONCURRENCY` (default 1);
  raise it only when tasks are genuinely isolated (e.g. vcluster).
- **Some task `setup.sh` scripts race the `default` ServiceAccount on a fresh
  cluster.** `debug-app-logs` (and any task that applies a pod immediately after
  `kubectl create namespace`) can fail setup with
  `serviceaccount "default" not found` on a brand-new kind cluster — the SA token
  controller hasn't created `default` yet. The harness then aborts the task
  *before the agent runs* (`result: ""`, `error: running command …/setup.sh: exit
  status 1`) — this is an **upstream task bug, not an omnis failure**; score it as a
  non-scored setup error. It's usually transient (a warmed/reused cluster clears
  it); a real fix would add a `kubectl -n <ns> wait`/retry for the SA in the
  upstream `setup.sh`.
- **`omnis-agent` leaks its spawned per-task server when the harness hard-kills it
  on a task timeout.** Some gatekeeper tasks declare a short `timeout:` in their own
  `task.yaml` (e.g. `allowed-reposv2`, `pod-disruption-budget` → `5m`; the harness
  default is 10m). When the agent exceeds *that* limit, the harness SIGKILLs
  `omnis-agent` **before** its own `OMNIS_BENCH_DEADLINE` (default 600s) and cleanup
  path run — so the dedicated omnis-server it spawned (isolation-mode tasks) is
  **orphaned** (reparented to systemd, still bound to the deleted task kubeconfig),
  along with its `/tmp/omnis-kab-*` `OMNIS_HOME`. Symptom: the task's `results.yaml`
  says `task timed out after 5m0s` and `log.txt` has **no `omnis-agent: usage`
  footer** (so its cost is unaccounted). Harmless zombies (no Pass@k impact — each
  task uses its own cluster/port), but they accumulate across runs. After a run,
  sweep leftovers: `pgrep -af omnis-server` → kill any bound to `/tmp/omnis-kab-*`
  (leave the dev `:8080` instance), then `rm -rf /tmp/omnis-kab-*`. A real fix would
  put the child server in its own process group + a SIGTERM handler in `omnis-agent`,
  and/or have `run.sh` `cleanup()` reap `omnis-kab-*` at end-of-run.
- **Layer an omnis config override cheaply** via `OMNIS_HOME=<tmp>` holding just
  the file you want to override (e.g. `permissions.json`) — the chain picks it up
  above `/etc/omnis` while everything else falls through.
- **Verify per-tier price / recorded model** in any model comparison; do not trust
  that a reload took effect.
- **The ChapsVision gateway caches responses, so `--repeat N` does not sample
  variance.** Replies carry `x-litellm-cache-key`, and two identical requests return
  the *same* `chatcmpl-id` byte-for-byte (no `x-litellm-response-cost` header on a
  hit). A bench task's prompt is fixed, so every repeat after the first replays the
  cache: measured on `squad-bench --suite --repeat 2` over `balanced`, repeats ran
  ~5× faster and ~40% cheaper, and both `search-single` repeats were rigorously
  identical (101 `token_events`, $0.0123, same tool counts). **Only the first (cold)
  sample is a measurement.** Tasks whose sub-agents pull external content
  (`docs-lookup` → WebSearch/WebFetch) escape it, since the downstream prompts
  differ. To sample for real, vary the prompt per run (nonce) or disable the cache
  server-side. Same trap when probing a model endpoint by hand — a fixed prompt
  replays an earlier verdict, which can turn a *fixed* endpoint into a false negative.
- **A gateway alias can silently lose a capability its own `/model/info` advertises.**
  LiteLLM 1.93 stripped `tools` from every `scaleway/*` route because the deployment
  used the model id Scaleway exposes (`qwen3.6-35b-a3b`) while litellm's cost map keys
  it vendor-prefixed (`scaleway/qwen/qwen3.6-35b-a3b`) — the miss reads as "no
  function calling" and the param is dropped without a warning. Full diagnosis and the
  JSON-only fix (cost-map `aliases`) in
  `reports/gateway-balanced-tool-calling-2026-08-13.md`. Lesson for benching: when a
  model suddenly "narrates instead of acting", run `model-probe` against the endpoint
  **and** the same model direct at its provider before blaming the squad or the model.
