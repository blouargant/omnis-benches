# k8s-ai-bench — Full Run Report

**Date:** 2026-07-05
**Agent under test:** omnis (kubernetes squad, shipped unchanged, `bypassPermissions`)
**Scope:** Full suite — main (24 scored) + gatekeeper (31)
**Harness:** gke-labs/k8s-ai-bench @ `main`, `--concurrency 1` (sequential), kind ephemeral clusters

## TL;DR

| Suite | Pass@1 | Rate | Cost | Wall |
|---|---|---|---:|---:|
| **Main** | **24 / 24** | **100%** | $15.61 | ~53 min |
| **Gatekeeper** | **24 / 31** | **77.4%** | $5.79 | ~46 min |
| **Total** | **48 / 55** | **87.3%** | **$21.41** | **1 h 39 m** |

omnis **swept the entire main suite (24/24)** — every create/fix/scale/debug/lifecycle
task passed. All 7 losses are in the gatekeeper suite and are **audit-precision** errors
(over- or under-reporting policy violations), not execution or infra failures. Run window
12:30:54Z → 14:10:06Z. `fix-oomkilled` is disabled upstream, so 55 tasks were scored, not 56.

---

## 1. Environment

| Component | Version |
|---|---|
| k8s-ai-bench | gke-labs/k8s-ai-bench @ `main` |
| kind | v0.32.0 (node kindest/node:v1.36.1) |
| kubectl | v1.33.11 · helm v4.2.2 · go 1.26.0 |
| squad | `kubernetes` (shipped), `bench-permissions.json` = `bypassPermissions` |
| model fleet | omnis's tiered fleet (premium leader + cheap sub-agents — see §5) |
| concurrency | **1 (sequential)** via the `CONCURRENCY` knob added to `run.sh` |

## 2. Methodology

Two phases, run back-to-back, **sequentially**, into **separate output dirs** (the task id
`horizontal-pod-autoscaler` exists in *both* suites, so a shared dir would clobber one):

- **Phase 1 — main / shared-cluster path** (`TASK_PATTERN='^[^g]'`, `.build/full-main`).
  One kind cluster (`k8s-ai-bench-eval`) + **one** omnis-server; every task opens a session on it.
- **Phase 2 — gatekeeper / `isolation: cluster` path** (`TASKS_DIR=…/tasks/gatekeeper`,
  `.build/full-gatekeeper`). The harness creates a **dedicated throwaway cluster per task**;
  `omnis-agent` spawns a dedicated omnis-server for each, installs Gatekeeper/OPA, runs, tears down.

> **Why sequential.** The upstream harness treats `--concurrency 0` (its default) as
> *"auto = number of tasks"* — it runs **every task at once**. On the shared single-cluster/
> single-server kind path that produces resource contention + model-endpoint flooding → noisy
> pass/fail. `run.sh` now defaults to `CONCURRENCY=1`; this run used sequential throughout.

## 3. Results — Main suite (24 / 24 = 100%)

| Task | Result | Time | Cost |
|---|---|---:|---:|
| create-canary-deployment | ✅ | 3m23s | $0.85 |
| create-network-policy | ✅ | 1m07s | $0.39 |
| create-pod | ✅ | 59s | $0.18 |
| create-pod-mount-configmaps | ✅ | 39s | $0.29 |
| create-pod-resources-limits | ✅ | 36s | $0.28 |
| create-simple-rbac | ✅ | 1m17s | $0.76 |
| debug-app-logs | ✅ | 1m34s | $0.27 |
| deployment-traffic-switch | ✅ | 2m01s | $0.40 |
| fix-crashloop | ✅ | 2m19s | $0.31 |
| fix-image-pull | ✅ | 2m10s | $0.35 |
| fix-pending-pod | ✅ | 2m36s | $0.45 |
| fix-probes | ✅ | 2m40s | $0.43 |
| fix-rbac-wrong-resource | ✅ | 1m43s | $0.31 |
| fix-service-routing | ✅ | 2m11s | $0.66 |
| fix-service-with-no-endpoints | ✅ | 3m40s | $1.30 |
| horizontal-pod-autoscaler | ✅ | 1m05s | $0.55 |
| list-images-for-pods | ✅ | 1m27s | $0.26 |
| multi-container-pod-communication | ✅ | 4m10s | $1.10 |
| resize-pvc | ✅ | 4m00s | $1.85 |
| rolling-update-deployment | ✅ | 2m11s | $0.31 |
| scale-deployment | ✅ | 1m26s | $0.26 |
| scale-down-deployment | ✅ | 1m09s | $0.25 |
| setup-dev-cluster | ✅ | 4m19s | $2.51 |
| statefulset-lifecycle | ✅ | 3m22s | $1.32 |

*(`fix-oomkilled` disabled upstream — not scored.)* No setup errors this run: `debug-app-logs`,
which aborted on a fresh-cluster `default`-ServiceAccount race during the smoke run, passed
here on the warmed cluster (1m34s) — confirming that race is transient.

## 4. Results — Gatekeeper suite (24 / 31 = 77.4%)

| Task | Result | Time | Cost |
|---|---|---:|---:|
| allowed-ip | ✅ | 58s | $0.17 |
| allowed-repos | ❌ | 4m55s | $0.17 |
| allowed-reposv2 | ✅ | 5m13s | $0.15 |
| automount-serviceaccount-token | ❌ | 1m02s | $0.13 |
| block-endpoint-default-role | ✅ | 1m09s | $0.15 |
| block-loadbalancer-services | ✅ | 50s | $0.12 |
| block-wildcard-ingress | ✅ | 1m01s | $0.22 |
| container-cpu-requests-memory-limits-and-requests | ✅ | 1m02s | $0.17 |
| container-image-must-have-digest | ✅ | 1m32s | $0.16 |
| container-limits | ✅ | 1m30s | $0.18 |
| container-limits-and-requests | ✅ | 1m22s | $0.16 |
| container-limits-ignore-cpu | ❌ | 1m17s | $0.28 |
| container-requests | ✅ | 1m27s | $0.16 |
| disallow-anonymous | ❌ | 49s | $0.13 |
| disallow-interactive | ✅ | 54s | $0.12 |
| disallowed-tags | ❌ | 1m31s | $0.16 |
| ephemeral-storage-limit | ✅ | 1m25s | $0.19 |
| horizontal-pod-autoscaler | ✅ | 1m05s | $0.18 |
| memory-and-cpu-ratios | ✅ | 1m30s | $0.29 |
| memory-ratio-only | ✅ | 1m18s | $0.28 |
| must-have-key | ✅ | 59s | $0.12 |
| must-have-owner | ✅ | 57s | $0.13 |
| must-have-set-of-annotations | ✅ | 1m13s | $0.16 |
| pod-disruption-budget | ❌ | 2m13s | $0.27 |
| replica-limit | ✅ | 1m03s | $0.12 |
| repo-must-not-be-k8s-gcr-io | ✅ | 1m13s | $0.15 |
| required-probes | ❌ | 1m37s | $0.43 |
| tls-optional | ✅ | 1m14s | $0.16 |
| tls-required | ✅ | 1m09s | $0.32 |
| unique-ingress-host | ✅ | 1m17s | $0.17 |
| unique-service-selector | ✅ | 1m00s | $0.17 |

## 5. Gatekeeper failure analysis

These are **read-only audit tasks**: the agent is asked to list resources that *violate* a
policy, one `VIOLATING: <name>` line each, and is scored by `expect` substrings
(`contains`/`notContains`) — the empty `verify.sh` is not used. The tasks are deliberately
seeded with **compliant decoys** (to catch over-reporting) and **subtle violations** (to catch
under-reporting). The squad's audits are directionally right but imprecise on the edges:

**False positives — flagged a compliant/decoy resource (4):**

| Task | What happened |
|---|---|
| automount-serviceaccount-token | Flagged `resource-001` (compliant) alongside the real `resource-002`. |
| container-limits-ignore-cpu | Flagged `resource-001` (compliant) as well as `resource-002`. |
| disallowed-tags | Correctly found `resource-003…006` but **also** flagged compliant `resource-002`. |
| disallow-anonymous | Flagged `resource-001` in addition to `resource-002`. **Partly a task ambiguity** — see below. |

**False negatives — missed a real violation (3):**

| Task | What happened |
|---|---|
| allowed-repos | Missed `resource-003`: it inspected only the main container (`openpolicyagent/opa` → compliant) and **overlooked the `initContainer` running `nginx`**, which is the actual violation. |
| pod-disruption-budget | Found `resource-002` but **missed `resource-007`** (and named a PDB by an unexpected string), so the required `resource-007` match failed. |
| required-probes | Found `resource-002` but **missed `resource-003`**, whose probe coverage is incomplete at the container level. |

**Recurring root causes:**
1. **Fields off the happy path get skipped** — `initContainers` (allowed-repos) is the clearest
   example; the agent audited `spec.containers` only.
2. **Over-eager matching on borderline resources** — four failures flag a decoy the graders
   intentionally planted as compliant.
3. **Rule-interpretation edge cases** are sometimes ambiguous in the *task itself*:
   - **disallow-anonymous:** both `resource-001` and `resource-002` bind
     `system:unauthenticated`; only `resource-002` also binds `system:anonymous`. The prompt
     says to flag `system:anonymous` **or** `system:unauthenticated`, so the agent flagging
     `resource-001` is *defensible per the prompt wording* even though the grader wants only
     `resource-002`. This is at least as much a task-clarity issue as an agent error.
   - **required-probes:** "missing **both** a readiness and a liveness probe" is ambiguous
     between per-pod and per-container scope; the agent read it more narrowly than the grader.

So of the 7 losses, ~2–3 are clean agent misses (notably the `initContainer` blind spot),
while the rest mix genuine over-reporting with under-specified task wording. None are
execution/permission/infra failures.

## 6. Cost & token economics

| Metric | Value |
|---|---|
| Total cost | **$21.41** ($15.61 main + $5.79 gatekeeper) |
| Avg cost / task | $0.65 main · $0.19 gatekeeper |
| Prompt tokens | 9,132,868 |
| Output tokens | 151,766 |
| Cache-read tokens | **0** |

**Per-agent (whole run):**

| Agent | Prompt tok | Output tok | Calls | Role |
|---|---:|---:|---:|---|
| k8s_leader | 5,886,442 | 75,984 | 372 | orchestrates; **premium model → dominates cost** |
| k8s_investigator | 2,263,890 | 51,571 | 304 | read-only diagnosis (cheap tier) |
| k8s_editor | 956,958 | 23,011 | 154 | mutations (cheap tier) |
| k8s_cleaner | 25,578 | 1,200 | 6 | cleanup (cheap tier) |

Two things stand out:
- **The leader dominates spend.** It holds ~64% of prompt tokens and, on the premium tier,
  the overwhelming majority of dollar cost — the worker agents doing the actual kubectl work
  are ~50–70× cheaper per token. Main-suite tasks cost more than gatekeeper ones despite being
  fewer, because they are multi-agent (leader → investigator → editor, with mutation loops),
  whereas gatekeeper audits are mostly leader-only (3–9 calls) and read-only.
- **`cache_read_tok = 0` across all 55 tasks** — no prompt caching was in effect. Given the
  leader re-sends a large, largely-static system/skill context every call, enabling prompt
  caching is the single most promising cost lever here.

## 7. Findings & recommendations

1. **Main-suite competence is solid: 24/24.** Create, fix, scale, debug, traffic-switch,
   PVC resize, statefulset and dev-cluster setup all pass with the shipped squad — no narration-
   instead-of-acting failures, which the `bypassPermissions` config successfully avoids.
2. **Gatekeeper gap is audit precision, not capability.** To lift the 77% → higher, the squad's
   audit playbook should (a) enumerate **all** container types incl. `initContainers`/
   `ephemeralContainers`, and (b) be more conservative about flagging borderline resources.
   This is a prompt/skill change (tighten the k8s-audit procedure), not a model change.
3. **File upstream task-clarity issues** for `disallow-anonymous` (prompt vs. expected
   contradiction on `system:unauthenticated`) and `required-probes` ("missing both" scope) —
   these penalize a defensible reading.
4. **Enable prompt caching** for the leader — `cache_read_tok=0` everywhere means the biggest
   cost line (leader re-sending static context 372×) is fully uncached.
5. **Infra & harness are healthy.** Sequential execution, shared-server multiplexing (main),
   per-task dedicated servers + OPA installs + cluster teardowns (gatekeeper) all worked;
   no leftover clusters/processes; the `debug-app-logs` fresh-cluster SA race is transient.

---

*Raw results (gitignored): `k8s-ai-bench/.build/full-main/<task>/` and
`.build/full-gatekeeper/<task>/` — each has `results.yaml`, `log.txt`, `trace.yaml`.*
*Pipeline validation: see [k8s-ai-bench-smoke-2026-07-05.md](k8s-ai-bench-smoke-2026-07-05.md).*
