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
  **Cache-aware billing, same fix as squad-bench's `note_model` (commit
  `6cb1466`) — mirrored here in `note_usage`.** `prompt_tokens` (OpenAI usage
  convention) already **includes** `cache_read_tokens` as a subset, not an
  addition; billing the full `prompt_tokens` at the input price AND
  `cache_read_tokens` at the cache-read price double-charges the cached
  portion. `note_usage` bills only the uncached remainder
  (`prompt_tok - cache_read_tok`, clamped at zero) at the input price;
  `cache_read_tok` pays the cache-read price. Same verified regression as
  squad-bench: 182311 prompt / 153089 cache-read (84% hit) / 3052 output at
  $3.15/$15.75/$0.30 per M reads **$0.668275** under the old formula, **$0.186045**
  under the correct one. **Any `omnis-agent: usage` summary or `--trace-path`
  footer captured before this fix carries an inflated cost for any agent whose
  `cache_read` is non-zero** (a zero-cache agent is unaffected); it can be
  recomputed from the retained `prompt`/`cache_read`/`out` fields the same way
  a pre-fix squad-bench JSONL record can (see squad-bench's README/CLAUDE.md
  note) — this file does not persist `cache_read_price_per_m` per agent, so
  recomputing a specific historical run needs that price looked up from the
  `models.json` active at the time. **Consequence for past conclusions:** any
  cost comparison drawn from `omnis-agent` runs before this fix (e.g. a
  cost-per-tier ratio) overstates the cost of whichever tier caches more
  heavily — `premium` was measured at 84% cache-hit in one such run, so a
  `premium`-vs-non-caching-tier ratio computed pre-fix is inflated on
  `premium`'s side. Do not recompute or rewrite historical `k8s-ai-bench`
  reports retroactively; treat pre-fix and post-fix cost figures as
  non-comparable. `omnis-agent`'s pure logic (`note_usage`, `usage_summary`)
  has unit coverage in `k8s-ai-bench/test_omnis_agent.py` — the script has no
  `.py` suffix (it must present as a `kubectl-ai`-shaped CLI binary), so the
  test module loads it via `importlib.machinery.SourceFileLoader` rather than
  a normal `import`.
- Env: `OMNIS_SERVER_BIN` (omnis-server binary), `OMNIS_BENCH_SQUAD` (default
  `kubernetes`), `OMNIS_BENCH_DEADLINE`. Running the full suite needs
  **kind + docker + go** (not auto-installed).
- Unit tests: `python3 -m unittest discover -s k8s-ai-bench` (stdlib only;
  covers `omnis-agent`'s pure logic only — no live cluster/server involved).

## Gotchas (hard-won)

- **`OMNIS_CONFIG_DIRS` does NOT redirect the omnis agent registry** — only config
  *files*. A per-agent `model_ref` edit in a custom config dir is ignored; the
  registry resolves from the default chain (`.agents` → `$HOME/.omnis` →
  `/etc/omnis`). To swap the model for a bench, use the **single-model override**
  in `models.json` (`override_model_ref` + `override_model_enabled`,
  hot-reloadable), and **always verify the recorded per-tier price actually
  changed** (each record's `models` block carries in/out `$/M`) before trusting a
  sweep — a silent no-op swap makes every tier look identical.
- **"hot-reloadable" does NOT cover a file edit to `override_model_enabled` — RESTART the
  bench server between arms.** Measured 2026-09-15 while building a two-arm squad-bench
  comparison: flipping `override_model_enabled` to `false` in the running server's
  `.agents/models.json` left the very next task still recording `in_per_m: 0.42 /
  out_per_m: 0.84` (the override tier). Only a restart picked it up. **This is the exact
  failure the price check exists to catch** — without it the "baseline" arm would have
  measured the override model while believing it measured the defaults, and the two arms
  would have looked identical, which reads as "the model makes no difference" rather than
  "the swap never happened". Recompute the cost from each record's own
  `prompt_tok`/`out_tok` against the printed `$/M` before trusting ANY arm.
- **Defaults of the `Coding` squad, for sizing a baseline** (read off a record's `models`
  block on 2026-09-15, since the agents are `builtin` and carry no readable `model_ref`
  in `~/.omnis/registry/agents/*/agent.json`): `coder` = **premium** ($3.15/$15.75 per M),
  `code_scout` = **simple** ($0.2625/$0.525), `code_docs` = **balanced** ($0.26/$1.58).
  A 4-task `--suite` baseline arm costs ~$0.19.
- **`SERPER_KEY` is absent from the root `.env` but lives in the dev server's own
  environment.** `~/.omnis/agents.json` declares `"serper_key": "SERPER_KEY"` (an env-var
  reference), and that variable is in neither the shell nor `.env` — so a freshly spawned
  bench server gets no paid backend and web tasks silently fall back to DuckDuckGo. It
  can be read from the running dev server (`tr '\0' '\n' < /proc/<pid>/environ`) as a
  stopgap, but **it belongs in the root `.env`** per this file's own single-mechanism
  rule.
- **squad-bench never answers `ask_user` — and now fails fast instead of hanging.**
  A tool call that raises a permission prompt used to burn the whole deadline and
  come back as `cancelled`, which reads like a model failure. Since 2026-09-05 the
  first `ask_user` frame **aborts the run**: `consume` stops the stream, `status`
  becomes **`ask_user`** (a new value alongside `done`/`timeout`/`cancelled`/`error`),
  a multi-turn task does not send its remaining prompts, and the session is
  cancelled. Measured end-to-end: 2 s instead of a 240 s deadline. `omnis-agent`
  does the same and exits **3** with the prompt text on stderr. Conversely **no
  mutation can execute** (the bench can't approve it). For cluster-touching squad-bench tasks,
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
- **That August fix FREEZES the cost map, so every Scaleway model added afterwards is
  born with `tools` stripped.** FIXED for DeepSeek on 2026-09-15 — but **NOT by the
  `openai/` route**, contrary to what this entry first claimed. Re-probed after the fix:
  **9 pass / 0 fail / 0 warn**, all 4 critical tool checks green, `tool_choice=required`
  and parallel tool calls working too, no regression on the siblings
  (Balanced/High/Simple/qwen3.6/mistral-medium all 4 pass). **The route still resolves to
  the Scaleway provider** — proven twice: an unknown kwarg AND an upstream 400 both come
  back as `litellm.APIConnectionError: ScalewayException` (an `openai/` route would raise
  `OpenAIException`), and `litellm_params.model` still reads
  `scaleway/deepseek-v4-flash-0731`. The `openai/` detour measured at 11:27 was **rolled
  back on purpose** (confirmed by the user) — this is NOT the model-card-edit trap below
  firing; `scaleway/` is the intended configuration. **What this proves is that the COST MAP was fixed, not the
  route**: on the Scaleway JSON-provider path `tools` survives only if
  `supports_function_calling(model, custom_llm_provider="scaleway")` resolves True, which
  requires the key in the *effective* cost map. It resolves now and did not yesterday,
  while the card's `supports_*` flags were **identical on both days** — so the card is not
  the mechanism, and the served map must now carry `scaleway/deepseek-v4-flash-0731`
  (either the §4 one-entry hot patch or a refresh from upstream). The 6 short-id aliases
  are still in it too, since the siblings still pass. **So the structural remedy was NOT
  applied**: all 11 `scaleway/*` routes still hang off the
  August snapshot, and the next Scaleway model will be born broken again unless its card
  carries explicit capability metadata. Cheapest working policy — declare
  `supports_function_calling` + `max_input_tokens`/`max_output_tokens` on every new model
  card, then `model-probe --only tools` before wiring it into a squad.
  Original diagnosis, verified 2026-09-15 on `deepseek-v4-flash-scaleway`
  (deployed 2026-09-14): gateway **0/4** critical tool checks, Scaleway direct **7/7** —
  the model is fine, the gateway drops the param. The cause is *not* August's
  vendor-prefix mismatch, and the proof is a pair of facts admitting one explanation:
  the routes that **work** declare SHORT ids (`scaleway/qwen3.6-35b-a3b`) which exist
  **nowhere** in the current upstream cost map (not as keys, not as `aliases`), while
  the route that **fails** declares `scaleway/deepseek-v4-flash-0731`, which upstream
  **does** carry with `supports_function_calling: true`. Reading the upstream map would
  give the exact opposite result — so the gateway serves the **patched snapshot from
  2026-08-13**, which holds the 6 aliases but predates the DeepSeek entry.
  Consequence: **run `model-probe --only tools` against the gateway for every newly
  added `scaleway/*` model before wiring it into a squad** — a stripped `tools` makes
  agents narrate their plan instead of acting, which reads as a prompt or model problem
  and is expensive to chase. The durable fix is to stop depending on the cost map at
  all: the `openai/` route pattern hard-codes the tool params and never consults it.
  Full diagnosis, the one-entry hot patch, and the post-fix verification (§8) in
  `reports/gateway-deepseek-tool-calling-2026-09-15.md`.
- **DeepSeek's prompt cache is best-effort BY DESIGN — ~60% on a hammered prefix, but
  only 3.7% on real omnis load, and that gap is structural, not a bug.** Scaleway
  documents it: caching uses "heuristics that optimize both throughput and availability",
  "evicts it based on request frequency", and promises "a cache hit ratio between 50% and
  90%, though this value is not guaranteed". Measured 2026-09-15 on Scaleway direct with
  a unique cold prefix: **24/40 hits, windows of ten reading 6, 5, 7, 6** — it PLATEAUS
  near 60%, it does not warm toward 100% (a 24-call sample looked like a warming curve;
  40 calls refuted it). Still hits after 5 min idle (4/10), and **9/10 right after an
  8-way parallel burst** — concurrent calls warm several replicas at once, which is the
  only lever found. Latency corroborates independently: hits bottom out at ~320 ms,
  misses never went below 681 ms, so `cached_tokens` is honest. Cached volume is
  quantized to 128-token blocks. **On omnis the effective ratio is 3.7%**
  (9984/267581 tok over a squad-bench arm) because a prefix is only sent **2-7 times**
  before it is never seen again — `coder` (always `calls=2`) hit 0/4 tasks, `code_scout`
  (3-7 calls) hit 2 of 3. The documented band is for *recurring prefixes at volume*; a
  short agent session with a fresh prefix is the worst case, so **an isolated bench run
  structurally understates production caching** and the cache is a measurement
  CONFOUND worth ~5x on the cached share. Full investigation + reusable measurement
  script: `reports/deepseek-prompt-cache-2026-09-15.md` (+ `-probe.py`).
- **DO NOT re-investigate omnis's `cache_control` markers — tested, REFUTED.**
  `core/llm/openai.go:296` `markCacheablePrefix` marks `messages[0]` and the **last**
  message, and `markMessageCacheable` converts a string body to array form to host the
  annotation — so the previously-marked message reverts to a plain string on the next
  turn, and a proxy capture of real omnis traffic shows the common prefix between two
  consecutive same-agent requests dropping to **54-68% of the bytes** even though
  `system` and `tools` are byte-identical. It looks damning and it is a red herring:
  warming the cache with the STRING form and then switching to the LIST form still hit
  **7/12 (58%)** instead of restarting cold, and `prompt_tok` matched to within ±2
  (13628/13627/13626/13627). **Both forms tokenize identically** — the chat template
  normalizes content parts, and `cache_control` (an Anthropic convention) is inert on
  this endpoint. The byte diff compared JSON, not tokens.
- **Measuring this cache: ≥20 calls, a unique prefix nonce, and publish the SEQUENCE.**
  At 6 calls the answer ranges from 0% to 100%: a first sample read 0/3 through the
  gateway vs 1/3 direct, which nearly became a written-up "the gateway breaks caching"
  defect — 6 calls per rail then gave 3/6 on BOTH. Reuse the prefix from an earlier
  measurement and you inherit a warm state while believing you started cold. Report
  `cache_read_tok / prompt_tok` over the REAL workload, never a synthetic hammered
  prefix: the two differ by 16x (60% vs 3.7%).
- **DeepSeek's `/model/info` was FIXED 2026-09-15 — omnis now prefills the safe context
  by itself, and `max_tokens` is the leftover trap.** It used to advertise
  `max_output_tokens: 256000` while the provider rejects anything above **32768**
  (boundary verified exactly: 32768 -> OK, 32769 -> `payload validation:
  max_completion_tokens is limited to 32768 for deepseek-v4-flash-0731`, an unbilled
  400). It now declares `max_output_tokens: 32768` **and** `max_input_tokens: 229376`
  (= 262144 - 32768), so `server/provider_models.go`'s `ctxLen := mi.MaxInputTokens;
  if ctxLen == 0 { ctxLen = mi.MaxTokens }` yields **229376** — the shipped-`balanced`
  output-reservation trap can no longer happen for this model via prefill, and the
  cache-read price is picked up with it. **But `max_tokens` is still 256000**, where
  LiteLLM convention (and the upstream entry) makes it mirror `max_output_tokens`
  (32768): harmless for omnis, which reads it only when `max_input_tokens` is zero, yet
  a live mine for any client reading it as the output budget. Also note **editing a
  model's `model_info` rewrites the whole LiteLLM deployment**, so it can silently
  revert `litellm_params.model` — re-run `model-probe --only tools` after every edit to
  a model's card (it did not revert this time: 4 pass / 0 fail). **The 400-masked-as-500
  is NOT fixed** — re-measured 2026-09-15 after the fix: `temperature: 999` returns a
  clean `400 BadRequestError` on Scaleway direct but a **500**
  `litellm.APIConnectionError: ScalewayException` through the gateway. Separately, an
  over-cap `max_tokens` no longer errors at all (9999999 -> **200**), so LiteLLM now
  clamps or drops it against the declared `max_output_tokens` — meaning **the
  unbilled-400 trick for discovering a model's real output cap no longer works through
  the gateway**. Use the direct rail for that.
- **A model's `context_length` must leave room for the output reservation — the
  shipped `balanced` value does not.** omnis asks for `max_completion_tokens` on
  top of the prompt, and the provider validates the *sum* against its context
  window. Scaleway serves `deepseek-v4-flash-0731` and `qwen3.6-35b-a3b` (=
  `Balanced`) at **262144** tokens with a **32768** output cap (`qwen3.5-397b-a17b`
  = `High`: 16384; `gemma-4-26b-a4b-it` = `Simple`: 32768) — provoke the numbers
  cheaply with an unbilled validation error: POST `/chat/completions` with
  `max_tokens: 9999999` and read the 400. `/etc/omnis/models.json` declares
  `balanced.context_length: 256000`, leaving only 6144 tokens of headroom for a
  32768-token output — so a full-window turn fails with `400 … maximum context
  length is 262144 … you requested 32768 output tokens`. The safe value is
  **229376** (262144 − 32768). Latent in production: it only fires when an agent
  actually fills its window (observed on a runaway `web-deep-ds7` run). Verified
  2026-09-01, `reports/deepseek-v4-flash-scaleway-2026-09-01.md`.
- **Override models.json with a `.agents/` dir in the bench server's CWD — never by
  editing `~/.omnis/models.json`.** `loadModelsConfig` calls
  `configedit.MergedBytes`, which **deep-merges every layer** of the chain
  (`.agents` → `$OMNIS_HOME` → `/etc/omnis`), and `.agents` is CWD-relative and
  highest-precedence. So launching a dedicated `omnis-server` from a temp dir
  holding just `.agents/models.json` adds providers/models and flips
  `override_model_ref` **without touching the user's config** and without the
  `OMNIS_HOME` trap (which would also move `registry/agents`, silently swapping the
  very agents under test). Keep `HOME` unchanged so `~/.omnis/registry/agents` is
  what gets benched. Run the server in the **foreground** (`OMNIS_SERVER_ADDR=
  127.0.0.1:<port>`): `$OMNIS_HOME/omnis-server.pid` is written only by the
  `omnis-server start` daemon path, so a foreground instance never collides with a
  dev server the user already has running.
- **Scaleway direct is the honest rail for comparing gateway `scaleway/*` tiers.**
  `Balanced`/`High`/`Simple` are Scaleway routes, so re-measuring them at
  `SCALEWAY_API_BASE_URL` gives the same network path as a candidate Scaleway model
  **and escapes the gateway's response cache** — `--repeat` yields real samples
  there, unlike through the gateway. The gateway applies a flat **EUR→USD ×1.05
  with no markup** on Scaleway models (checked rung by rung against Scaleway's
  public grid), so prices measured on the direct rail transfer to gateway economics
  unchanged. Note Scaleway prices prompt-cache reads **only for deepseek** — the
  qwen tiers report `cache_read_tok: 0` across a whole campaign, so omitting
  `cached_input_token_price_per_million` for them is faithful, not a config gap.
- **`OMNIS_CONFIG_PATH` in the ambient shell silently disables config merging for
  `agents.json` — and with it the paid search backend.** The user profile exports
  `OMNIS_CONFIG_PATH=/etc/omnis/agents.json` (the dev server on :8081 carries it
  too). That is omnis's **explicit bypass**: `loadRuntimeConfig` reads that one
  file *verbatim* and skips `configedit.MergedBytes` entirely, so `~/.omnis/agents.json`
  never contributes. `/etc/omnis/agents.json` declares no `serper_key` (only the
  user layer does), so a bench server inherits **no Serper backend** and web
  agents fall back to DuckDuckGo — surfacing as `deadline exceeded` / `timeout`
  in `subagent_errors`, which `campaign.mark_search_degraded` then flags. It also
  means custom squads dropped into a `.agents/agents.json` are **ignored**
  (observed: `editor-solo`/`cleaner-solo` absent from `/api/squads` and rejected
  by `POST /api/sessions`). Before any bench, either export
  `OMNIS_CONFIG_PATH=<your agents.json>` or unset it so the chain merges. `SERPER_KEY`
  is also missing from the root `.env` and should be added (CLAUDE.md mandates the
  root-`.env` mechanism), **but adding it alone does not fix this** — the variable
  was present in the environment and still unread. Diagnosed 2026-09-01;
  `reports/deepseek-v4-flash-scaleway-2026-09-01.md` §10 records the campaign it
  invalidated. Note `models.json` and `permissions.json` have no such bypass — they
  merge normally, which is why a `.agents/models.json` tier override works while a
  `.agents/agents.json` squad addition does not.
- **A k8s-ai-bench run drops agent-written manifests into the repo working copy.**
  `run.sh` executes from `k8s-ai-bench/`, so that is the agent's CWD, and any
  manifest the squad writes with the Write tool lands there — a 24-task run left
  `pod1.yaml`, `hpa-web-app.yaml`, `communication-pod.yaml` and
  `create-simple-rbac-rbac.yaml` as untracked files. They are not in
  `k8s-ai-bench/.gitignore` (which only covers `.build/`, `.bench-home/`,
  `.k8s-ai-bench/`, `__pycache__/`), so they show up in `git status` and are easy
  to commit by accident. Sweep them after a run, or add `*.yaml` to that
  `.gitignore` — nothing tracked in that directory is a YAML file.
- **To sweep a model tier through k8s-ai-bench, inject the config with
  `OMNIS_SYSTEM_CONFIG_DIR`, not `.agents/` or `OMNIS_HOME`.** `run.sh` owns the
  shared server's `OMNIS_HOME` (`mktemp -d`, into which it copies only
  `bench-permissions.json`), so there is no user layer to write into, and its CWD
  is the `k8s-ai-bench/` dir inside the repo. Point `OMNIS_SYSTEM_CONFIG_DIR` at a
  `cp -a` of `/etc/omnis` with a patched `models.json`: it replaces only the system
  layer, leaves `.agents` and `$OMNIS_HOME` intact, carries the `registry/` the
  `k8s_*` agents resolve from, needs no edit to `run.sh`, and reaches both the
  shared server and the per-task isolation servers. Verify the swap from each
  task's `log.txt`: the `omnis-agent: usage` footer has no `$/M` column, so
  **recompute** each agent's cost from its own retained `prompt`/`cache_read`/`out`
  counts and compare with the printed `~$` (cache-aware:
  `(prompt-cache)*in + cache*cache_in + out*out`). Give each tier a **fresh kind
  cluster** — `run.sh` deletes it on exit unless `KEEP_CLUSTER=1`, so plain
  sequential invocations already do the right thing; reusing one would carry the
  previous tier's mutations into the next tier's `setup.sh`/`verify.sh`.
- **`omnis-agent`'s deadline must land BEFORE the harness's task timeout, or a
  stall is unaccounted.** Both defaulted to the same value — `omnis-agent`'s
  `OMNIS_BENCH_DEADLINE` is 600s and the harness allows 10m (`eval.go`:
  `timeout := 10 * time.Minute`) — so on a stalled session they fire together,
  the harness wins the race and SIGKILLs the agent before its cleanup path runs.
  Signature: `results.yaml` says `task timed out after 10m0s`, `log.txt` ends
  mid-sentence (typically right after the leader announces a delegation), there
  is **no `omnis-agent: usage` footer**, and the task contributes **$0** to the
  campaign total — which silently makes the run look cheaper. `run.sh` now
  exports **540**; tasks declaring a shorter timeout of their own (gatekeeper's
  `5m`) are still cut off by the harness. Observed 2026-09-06: 3 of 24 tasks.
- **A zero-cost task is not a cheap task — never compare campaign totals without
  pairing.** Because a killed task contributes $0, a run with more stalls reads
  as *less expensive*. The 2026-09-06 arm C total ($3.98 vs $4.37) was almost
  entirely this artefact: paired over the 21 tasks that produced a footer in
  both arms, cost moved −2% and Pass@1 was identical (19 vs 19). Compare only
  tasks with a footer on both sides.
- **`run.sh` used to `rm -rf` the shared server's log with its temp home.** It is
  the only server-side record of a run, and it was destroyed at exit — precisely
  for the failure it would explain (a session stalling mid-delegation leaves
  nothing in the task's own `log.txt`). It is now copied to
  `$OUTPUT_DIR/shared-server.log` before the home is removed.
- **MEASURED at identical config: this suite flips 5 of 24 verdicts and swings
  its behavioural counters 15-36% with NOTHING changed.** Two 24-task runs of
  the *same* binary, hook, instruction and model override (2026-09-06, arms C
  and C2, verified file by file before each launch), paired over the 21 tasks
  with a footer in both: delegations **−15%**, `kubectl diff` **−29%**,
  `kubectl apply` **−36%**, cost +9%, Pass@1 identical (19/19) while the raw
  Pass@1 read 19 vs 21. Flipping verdicts: `create-pod`, `fix-pending-pod`,
  `fix-service-routing`, `resize-pvc`, `statefulset-lifecycle`. Per-task
  durations swing as much (`debug-app-logs` 297s→88s, `scale-deployment`
  63s→156s). **Consequence: at k=1 nothing below ~1.4x on a behavioural counter
  or ±2 tasks on Pass@1 is resolvable.** Two casualties on record: a −45%
  delegation effect from a 4-task probe (the reviewer-dry-run hook fix)
  vanished at suite scale, and the A/B's "+26% delegations" (x1.26) does not
  clear the x1.18 same-config swing — only its `diff` x2.28 does. Always (1)
  **pair** — a killed task has no footer and counts $0, so the run that stalls
  most looks cheapest; (2) **repeat**; (3) never let a small probe size a gain,
  only establish that a code path activates. The validator's own tool traffic is
  also **invisible in `log.txt`** (only the leader/editor stream reaches the
  harness's stdout), so measuring guard behaviour needs an instrumented hook
  trace, not log greps.
- **`fix-oomkilled` is disabled upstream** (`Skipping disabled task` in the run
  log), so the main k8s-ai-bench suite scores **24 tasks, not 25**. Use 24 as the
  denominator when quoting Pass@1, and don't chase the "missing" task.
- **FIXED 2026-09-05 (omnis `3b5dd17`), kept because the signature is worth
  recognising: a sub-agent's `max_instances` semaphore used to be shared by every
  session on the server, so one stuck invocation starved all later sessions.** Found 2026-09-05 on
  the k8s change-validation layer and it invalidates a whole k8s-ai-bench run.
  `k8s_validator` declares `"max_instances": 1`; `build_subagents.go:295` wraps it
  in `newConcurrentAgentTool`, whose semaphore is `make(chan struct{}, max)`
  (`concurrent_agent_tool.go:67`). `acquire` **queues** rather than rejecting, and
  the release is a `defer` that an `inner.Run` which never returns never reaches.
  Crucially the scope is per **config generation**, not per session:
  `instance.go:143` builds `Squads map[string]*SquadInstance` once. k8s-ai-bench
  deliberately runs ONE shared server for all 24 tasks, so a single held token
  makes every later Kubernetes **mutation** block to the harness's 10m task
  timeout. Signature to recognise it: tasks succeed in run order until some rank,
  then EVERY mutating task times out at exactly `10m0s` with **zero**
  `[tool] k8s_validator` in `log.txt` and no `omnis-agent: usage` footer, while a
  read-only task (`list-images-for-pods`) keeps passing in the middle of the
  block. Cutover was task #10 (deepseek), #2 (balanced), #1 (high) — the rank
  decides the score, not the model. Contre-épreuve: the same `fix-crashloop` that
  times out at 10m in-campaign passes in **2m21s** against a fresh server. Do not
  read a model comparison out of such a run. **The fix makes the semaphore per
  session** (`concurrent_agent_tool.go` keys a `sessionSem` per session and prunes
  the map), so what keeps it contained is the harnesses' one-session-per-test
  shape: `bench.py`'s `run_task` opens AND deletes a session per run (per
  `--repeat` sample too), and `omnis-agent` opens one per invocation and now
  deletes it on every exit path. **Keep it that way** — a harness that reused a
  session across tests would rebuild the starvation inside that session. Full
  diagnosis of the original bug:
  `reports/omnis-k8s-validator-starvation-2026-09-05.md`.
- **The k8s validation hook is NOT a measurable cost — don't blame it.** Measured
  by wrapping `/etc/omnis/hooks/k8s-validate.py` in a timing shim inside an
  `OMNIS_SYSTEM_CONFIG_DIR` copy (the hook command is
  `${OMNIS_SYSTEM_CONFIG_DIR:-/etc/omnis}/hooks/k8s-validate.py`, so a relocated
  copy is picked up automatically): **65 invocations, 4.4s total, 3% of a 141s
  task, slowest single call 0.13s.** When a k8s run gets slow, instrument before
  accusing the guard.
- **The k8s guard's three headless blockers were fixed 2026-09-05; a bench must
  still declare itself.** Set **`OMNIS_NON_INTERACTIVE=1`** on any unattended run:
  `canEscalate` (`agent/hooks_ask.go`) then makes a hook escalation a terminal
  block ("this run is unattended") instead of an `ask_user` card nobody resolves.
  The other two fixes removed the refusals upstream, so in practice the env var
  never fires — measured 0 escalations over 72 tasks, against 11 the run before:
  `CONTAINER_ACCESS_VERBS` ("exec", "attach", "cp") now proves the INNER command
  read-only (`kubectl exec … -- cat f` allows, `-- sh -c '…'` and `attach -i`
  still refuse), and a `diff` that fails on a missing namespace now appends the
  remedy instead of dead-ending. Verify all three against a live cluster before a
  campaign — the hook's decisions depend on the cluster, so a probe without one
  gives false denies.
- **`create-pod`'s upstream `verify.sh` string-matches the image**, so
  `image: nginx:latest` fails where bare `nginx` passes — and the validation layer
  made every model write the explicit tag, because binding attestations to
  manifest CONTENT pushes agents from imperative commands to manifests. All three
  tiers failed it on 2026-09-06 for that reason alone. Score it as a task defect,
  not a model one, and use 22 as the discriminating denominator alongside
  `setup-dev-cluster`, which no tier has ever passed.
- **`--dry-run` is not a read path under the k8s guard.** `kubectl diff` is
  allowed; `kubectl apply --dry-run=server`, `kubectl apply --server-side
  --dry-run=server` and `helm upgrade --dry-run` are all denied (the last one
  demands a `k8s_validator` attestation). That is the inverted rule working as
  designed — prove read-only or refuse — but `k8s_editor`'s own description still
  promises "previews every change with kubectl/helm diff and dry-run", which is
  now half true. A model noticed mid-task: "The hook is flagging `kubectl apply`
  even for dry-run".
- **`README-kubernetes.md`'s permission snippet has two defects (both fixed
  2026-09-05, both latent since July).** (1) `permissions.ask` is a `valueList`,
  so layers **concatenate**: `"ask": []` removes nothing and `/etc/omnis`'s 33 ask
  rules — `Bash(rm *)` among them — stay live. squad-bench never answers
  `ask_user`, so an agent that writes then deletes a temp manifest hangs to the
  deadline. Use the `permissions.ask_removed` tombstone (removes by deep-equal)
  seeded from `/etc/omnis/permissions.json`'s own `ask` list. The k8s validation
  layer makes this fire often because it binds attestations to manifest CONTENT,
  pushing agents through files. (2) The deny regex `\bkubectl\b[^|;&]*\b(…|debug|
  …)\b` matches `debug` INSIDE `tmp-debug-shell` / `debug-probe` / `debug-cm` (the
  hyphen is a word boundary), denying the very reads `clean-identify` /
  `clean-suspect` exist to perform. Require a literal space before the verb —
  `[^|;&]*\s(verb)(\s|$)` — since RE2 has no lookbehind. Verified: all 4 real
  mutations still denied, all 3 reads pass.
- **Agents leave files in the bench's CWD, including a literal `$OMNIS_HOME/`
  directory.** omnis's own sub-agent briefing prompt tells agents to write briefs
  to `$OMNIS_HOME/logs/brief_<topic>.md`, but the Write tool does not expand shell
  variables, so a directory literally named `$OMNIS_HOME` appears in the working
  copy (seen holding `hpa-web-app.yaml` and `logs/reader-role*.yaml`). Sweep it
  along with the stray `*.yaml` manifests after every k8s run.
