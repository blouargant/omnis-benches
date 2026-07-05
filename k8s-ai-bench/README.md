# k8s-ai-bench × omnis

Run the [gke-labs **k8s-ai-bench**](https://github.com/gke-labs/k8s-ai-bench)
suite against omnis, so omnis is scored (Pass@1 / Pass@5 / Pass^5) on real
Kubernetes tasks — `create-pod`, `fix-crashloop`, `fix-oomkilled`,
`fix-pending-pod`, RBAC, network-policy, gatekeeper policies, … — on ephemeral
per-task clusters, **comparable head-to-head with other agents** (kubectl-ai, …).

This is a more complete, externally-maintained suite than our hand-rolled
`squad-bench/tasks-kubernetes.json` (which stays useful for cheap, cluster-safe
model-tier sweeps). Here the agent must *actually mutate* a throwaway cluster.

## How it plugs in

k8s-ai-bench drives an agent as a CLI binary shaped like `kubectl-ai`
(`--agent-bin`), invoking it per task with `--kubeconfig <path>` + `KUBECONFIG`
in the env and the task prompt on **stdin**, then scores the result with the
task's `verify.sh`.

**[`omnis-agent`](omnis-agent)** is that binary: a dependency-free Python client
that accepts the kubectl-ai flags and drives **omnis over its HTTP API**. Per
invocation it pins a session to the Kubernetes squad, sends the task, streams the
SSE, prints the transcript, and exits 0 on success. It is the single entry point.

Because omnis-server multiplexes many sessions, **[`run.sh`](run.sh) starts ONE
shared omnis-server for the whole run** (bound to a run-owned shared cluster it
creates and **deletes on exit**), and each task just opens a session on it via
`OMNIS_SERVER`. A task that declares its own cluster (`isolation: cluster`, e.g.
the gatekeeper suite) gets a **dedicated throwaway server** that `omnis-agent`
spawns and tears down, bound to that task's kubeconfig.

```
run.sh
  ├─ create kind cluster ──▶ start ONE shared omnis-server (KUBECONFIG=cluster,
  │                            Kubernetes squad, allow-all permissions)
  ▼
k8s-ai-bench  --agent-bin ./omnis-agent  --kubeconfig <shared>  (per task)
      │  stdin: "<task goal>"
      ▼
  omnis-agent ──HTTP/SSE──▶  new session on the shared server → task
      │                        → kubectl/helm on the cluster
      │  (isolation:cluster task → spawns its OWN throwaway server instead)
      └── prints transcript
      ▼
  verify.sh  ──▶  Pass@k
  ▼
run.sh (on exit): stop shared server + delete the kind cluster
```

Because the server's `KUBECONFIG` **is** the task cluster, omnis's kubectl/helm
target it by default — no `--kubeconfig` juggling, and the server can't reach any
other cluster.

### Design decisions (see `omnis-agent` header for details)

- **Shipped Kubernetes squad, unchanged.** We do **not** re-tune the agents for
  autonomy. Instead the bench server runs with a **temporary allow-everything
  [`bench-permissions.json`](bench-permissions.json)** (`bypassPermissions`), so
  the squad's mutations execute without a human to confirm. (If the squad's
  confirmation-oriented instructions cause it to propose-and-wait instead of
  acting, that shows up as failed tasks — an honest signal about the shipped
  squad.)
- **Fixed omnis fleet.** The harness's `--model` / `--llm-provider` are accepted
  and **ignored**; omnis uses its own configured fleet (the harness's model column
  is just a label). To sweep omnis models, change the omnis config, not the flag.
- **One server, many sessions (+ auto cluster teardown).** omnis-server handles
  concurrent sessions, so `run.sh` runs a **single** server for the whole run and
  each task opens a session on it — no per-task server boot. omnis's `kubectl`
  runs inside the *server* process, so the server binds `KUBECONFIG=<shared
  cluster>`; `run.sh` owns that cluster's lifecycle (creates it, hands the harness
  `--cluster-creation-policy DoNotCreate --kubeconfig <shared>`, and **deletes the
  cluster on exit** — the upstream harness never deletes it). Only
  `isolation: cluster` tasks (their own cluster) get a dedicated server, spawned
  and torn down by `omnis-agent`; the harness deletes those clusters itself.
  Override with `KEEP_CLUSTER=1` (keep the cluster) or `SHARED_CLUSTER=<name>`.
- **Token/cost accounting.** `omnis-agent` folds the stream's `turn_usage` frames
  into a per-agent tally (prompt / output / cache-read tokens, call count, and an
  estimated USD cost from the model's `$/M` prices — same math as squad-bench's
  `models` block). At end of task it writes a summary to **stderr** (lines prefixed
  `omnis-agent: usage …`) and, if `--trace-path` is set, appends the same summary
  as a footer to the trace file. stdout stays the answer text the harness scores,
  so this is diagnostic only and doesn't affect Pass@k.

## Prerequisites

Not auto-installed:

- **docker + kind** — `run.sh` creates one ephemeral kind cluster for the run
  (and `isolation: cluster` tasks get their own); all are torn down at the end.
- **kubectl + helm** on PATH — omnis's tools shell out to them.
- **go** — to build the upstream harness.
- **omnis-server** on PATH (or `OMNIS_SERVER_BIN=/path/to/omnis-server`).
- **model credentials in the environment** — whatever your omnis `models.json`
  reads (e.g. `OPENAI_BASE_URL` / `OPENAI_API_KEY`). Put them in the project-root
  **`omnis-benches/.env`** (gitignored); `run.sh` sources it automatically. (Or
  `source` them yourself before running — e.g. your omnis `.env`.)

## Run

```bash
# model credentials: put OPENAI_BASE_URL / OPENAI_API_KEY in omnis-benches/.env
# (gitignored) — run.sh sources it automatically. No manual `source` needed.
./run.sh                            # all tasks
TASK_PATTERN='fix' ./run.sh         # a subset (regex: 'fix', 'pod', 'scale', …)
```

`run.sh` clones + builds the upstream harness (pin a commit with `KAB_REF=<sha>`),
creates the shared kind cluster, starts one shared omnis-server, runs the harness
against `omnis-agent`, then deletes the cluster + server on exit. Results + JSONL
land in `.build/`; use the harness's `analyze` subcommand for the report. Knobs:
`KEEP_CLUSTER=1` (don't delete the cluster), `SHARED_CLUSTER=<name>`,
`CLUSTER_PROVIDER=vcluster` (falls back to a per-task server per isolated task),
`TASKS_DIR=<dir>` (see the gatekeeper caveat below).

```bash
# gatekeeper suite (nested one level deeper — point TASKS_DIR at it):
TASKS_DIR="$PWD/.k8s-ai-bench/tasks/gatekeeper" TASK_PATTERN='must-have-key' ./run.sh
```

### Driving omnis-agent directly (debug)

```bash
# omnis-agent spawns its own server bound to --kubeconfig (needs OMNIS_SERVER_BIN
# on PATH as `omnis-server`, and model creds in the env):
echo "Create a deployment named web with 2 nginx replicas in namespace demo." \
  | ./omnis-agent --kubeconfig /path/to/task.kubeconfig

# or drive an EXISTING server (skip the spawn) — its KUBECONFIG must already point
# at the cluster:
echo "..." | OMNIS_SERVER=http://127.0.0.1:8091 ./omnis-agent --kubeconfig ignored
```

Env knobs: `OMNIS_SERVER_BIN` (omnis-server binary; default `omnis-server` on
PATH), `OMNIS_SERVER` (drive an existing server instead of spawning),
`OMNIS_BENCH_SQUAD` (default `kubernetes`), `OMNIS_BENCH_DEADLINE` (seconds, 600).

## Caveats / limitations (v1)

- **Multi-step tasks**: omnis reads the task as one prompt, so a task's multiple
  script steps are sent to omnis as a single turn (omnis gets the full goal at
  once). Fine for single-goal tasks; a per-step session mode is a future add.
- **Shared server, concurrent sessions**: the run's tasks share one omnis-server
  (and one cluster), so a whole batch mutates the same cluster in parallel under
  distinct namespaces — same as before, but now through one server. Only
  `isolation: cluster` tasks still pay a per-task server boot (~1–3 s), since each
  is a genuinely separate cluster.
- **Gatekeeper suite is nested (flat loader).** The harness's task loader is flat
  — it expects `tasks/<id>/task.yaml` and **errors on any top-level dir without
  one**, notably `tasks/gatekeeper/` (its tasks live a level deeper). So a plain
  full `./run.sh` over `tasks/` aborts on `gatekeeper/`; run that suite separately
  with `TASKS_DIR=.../tasks/gatekeeper`. Every gatekeeper task is
  `isolation: cluster` (its own cluster → a dedicated omnis-server).
- **`analyze` / LLM-judge**: some k8s-ai-bench reporting may use its own judge
  model via `--llm-provider`/`--models`; those flags configure the *harness*, not
  omnis. Set them to something valid for your environment if the analyze step
  needs it.
