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
  `expect` substring or `/regex/`). Tasks in `squad-bench/tasks.json`;
  `cwd:"sandbox"` tasks run against a git-isolated temp copy of
  `squad-bench/sandbox/`.
- **Tune prompts on weak models first.** A cheap model that "gets lost" is usually
  a *prompt* problem — tighten the agent's `instruction.md` (numbered procedure +
  explicit stop conditions), reload, re-run, watch redispatches/over-search drop.
- `tasks-kubernetes.json` + `README-kubernetes.md`: the k8s_editor/k8s_cleaner
  model-tier sweep (leaderless-solo-squad + models.json-override methodology).

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

- **Dedicated server per task.** Per invocation it spawns a throwaway
  omnis-server with `KUBECONFIG=<--kubeconfig>` (so omnis's kubectl/helm target
  exactly that ephemeral cluster and can't reach any other), drives the Kubernetes
  squad over HTTP, then tears it down. `OMNIS_SERVER=<url>` overrides to drive an
  existing server (debug).
- **Shipped squad unchanged + allow-all permissions.** `bench-permissions.json`
  (`bypassPermissions`) is copied into the per-task `OMNIS_HOME` so the
  confirmation-oriented squad mutates the sandbox without a human. Known risk: the
  squad may narrate a plan instead of fully acting → low Pass@k is an honest
  signal, not a bug.
- **Fixed omnis fleet.** `--model` / `--llm-provider` are accepted and **ignored**
  (omnis uses its own fleet); the harness's model column is a label. To vary
  omnis's models, change the omnis config.
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
  different: it *wants* mutation, hence `bypassPermissions` + a per-task
  throwaway cluster.)
- **Layer an omnis config override cheaply** via `OMNIS_HOME=<tmp>` holding just
  the file you want to override (e.g. `permissions.json`) — the chain picks it up
  above `/etc/omnis` while everything else falls through.
- **Verify per-tier price / recorded model** in any model comparison; do not trust
  that a reload took effect.
