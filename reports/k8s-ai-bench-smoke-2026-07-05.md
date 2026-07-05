# k8s-ai-bench — Smoke Run Report

**Date:** 2026-07-05
**Agent under test:** omnis (kubernetes squad, shipped unchanged)
**Scope:** Smoke subset (5 tasks) to validate the pipeline end-to-end before a full run
**Result:** ✅ Pipeline healthy — **4/4 scorable tasks passed (Pass@1 = 100%)**; both execution paths validated.

---

## 1. Why a smoke run

The full suite is large and expensive to run:

| Suite | Tasks | Cluster model | Est. time | Est. cost |
|---|---|---|---|---|
| Main | 25 | one shared kind cluster | ~30–75 min | ~$12 |
| Gatekeeper | 31 | one throwaway cluster **per task** (+OPA) | ~3–6 h | ~$15 |

Before committing to that, this run exercises **both** code paths the harness has, on a
representative slice, to confirm the plumbing works and the numbers are trustworthy.

## 2. Environment

| Component | Version |
|---|---|
| kind | v0.32.0 (node image kindest/node:v1.36.1) |
| kubectl | v1.33.11 |
| helm | v4.2.2 |
| go | 1.26.0 |
| omnis-server | on `PATH` (shared-server-per-run mode) |
| squad | `kubernetes` (shipped), `bench-permissions.json` = `bypassPermissions` |
| model fleet | omnis's own tiered fleet (premium leader + cheap sub-agents — see §5) |

## 3. Methodology

Two phases, run back-to-back, **sequentially** (`--concurrency 1`), output under
`k8s-ai-bench/.build/smoke/`:

- **Phase A — main / shared-cluster path.** `run.sh` creates one kind cluster
  (`k8s-ai-bench-eval`), starts **one** omnis-server bound to it, and each task opens a
  session on that shared server. Tasks: `create-pod`, `fix-crashloop`,
  `scale-deployment`, `debug-app-logs`.
- **Phase B — `isolation: cluster` / gatekeeper path.** The harness creates a dedicated
  throwaway cluster for the task; `omnis-agent` spawns a **dedicated** omnis-server for it
  (its kube-context differs from `OMNIS_SHARED_CONTEXT`), installs Gatekeeper/OPA, runs,
  and tears the cluster down. Task: `must-have-key`.

> **Concurrency fix applied.** The upstream harness treats `--concurrency 0` (its default,
> and what `run.sh` previously used) as *"auto = number of tasks"* — i.e. it launches
> **every task at once**. On the shared single-cluster/single-server kind path that means
> parallel mutating tasks contending for one node and flooding the model endpoint → noisy,
> untrustworthy pass/fail. `run.sh` now defaults to sequential via a new `CONCURRENCY` env
> knob (`CONCURRENCY=1`); override with `CONCURRENCY=N` only if you know the tasks are
> isolated enough. This is the correct default for a benchmark report.

## 4. Results

| Task | Path | Result | Duration | Cost | Agents exercised |
|---|---|---|---:|---:|---|
| create-pod | shared | ✅ success | 1m05s | $0.186 | leader → editor |
| fix-crashloop | shared | ✅ success | 2m29s | $0.286 | leader → investigator → editor |
| scale-deployment | shared | ✅ success | 1m29s | $0.260 | leader → investigator → editor |
| must-have-key | isolation (gatekeeper) | ✅ success | 1m01s | $0.124 | leader |
| debug-app-logs | shared | ⚠️ setup error (not scored) | 7s | — | — (agent never ran) |

**Scorable Pass@1: 4/4 = 100%.** Total agent spend for the run: **≈ $0.86**.

### What the passes demonstrate
- **create-pod** — create-from-scratch: leader delegates to `k8s_editor`, which creates the
  namespace + nginx pod and waits for Ready.
- **fix-crashloop** — diagnose-and-remediate: leader → `k8s_investigator` (root-cause) →
  `k8s_editor` (fix), verified via `kubectl rollout status`. Longest task (multi-agent).
- **scale-deployment** — reads current replicas (1), correctly interprets "double" → 2,
  patches, verifies rollout.
- **must-have-key** — validates the **entire gatekeeper path**: dedicated server, OPA
  install, constraint task, and clean per-task cluster teardown.

## 5. Cost & token notes

The per-agent breakdown (from each trace's `omnis-agent: usage` footer) shows a clear
**tiered fleet**: for comparable token volumes the **leader** costs ~50–70× the
sub-agents (e.g. scale-deployment: `k8s_leader` ~$0.24 for 71k prompt tok vs `k8s_editor`
~$0.002 for 52k prompt tok). So run cost is dominated by leader turns, not by the
worker agents doing the kubectl work. `cache_read_tok` was 0 across the board — no prompt
caching was in play for this run.

## 6. Findings

1. **`debug-app-logs` has an upstream setup race — not an omnis failure.** Its `setup.sh`
   creates a namespace and *immediately* applies a pod referencing the namespace's
   `default` ServiceAccount. On a freshly-created kind cluster the SA token controller
   hasn't created `default` yet, so `kubectl apply` fails with
   `serviceaccount "default" not found` and the harness aborts the task **before the agent
   runs** (`result: ""`, `error: running command …/setup.sh: exit status 1`). This lives in
   the gitignored upstream clone (`.k8s-ai-bench/tasks/debug-app-logs/setup.sh`), not in
   this repo. Mitigation for a full run: it typically only bites when the cluster is brand
   new; re-running the task against an already-warmed shared cluster usually clears it. If
   it recurs, the upstream setup.sh needs a `kubectl -n <ns> wait` (or retry) for the
   default SA before applying the pod.
2. **Both execution paths are healthy.** Shared-server multiplexing (Phase A: three tasks
   reused `http://127.0.0.1:59521`) and the dedicated-server `isolation: cluster` path
   (Phase B) both worked, and **cleanup is correct** — no leftover kind clusters or
   omnis-server processes after the run.
3. **Concurrency default was unsafe for a shared cluster** — fixed (see §3).

## 7. Recommendation

The pipeline is trustworthy. Suggested next step is the **main suite (25 tasks)**, which
is what `run.sh` is built around and completes in ~30–75 min:

```bash
cd k8s-ai-bench
TASK_PATTERN='^[^g]' ./run.sh      # 25 main tasks, sequential, one shared cluster
```

(The `^[^g]` pattern is filtered *before* the file read, so it skips the `gatekeeper/`
directory and avoids the flat-loader abort.)

Run the heavier **gatekeeper suite (31 tasks, ~3–6 h)** separately when you want it:

```bash
TASKS_DIR=k8s-ai-bench/.k8s-ai-bench/tasks/gatekeeper ./k8s-ai-bench/run.sh
```

---

*Raw results (gitignored): `k8s-ai-bench/.build/smoke/<task>/{results.yaml,log.txt,trace.yaml}`.*
