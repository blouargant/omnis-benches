# k8s-ai-bench — Full Run Report

**Date:** 2026-07-06 (run window 07:33:17Z → 09:54:01Z)
**Agent under test:** omnis (kubernetes squad, shipped unchanged, `bypassPermissions`)
**Scope:** Full suite — main (24 scored) + gatekeeper (31)
**Harness:** gke-labs/k8s-ai-bench @ `main`, `--concurrency 1` (sequential), kind ephemeral clusters

> Full run the day after the two 2026-07-05 runs
> ([run 1](k8s-ai-bench-full-2026-07-05.md), [run 2](k8s-ai-bench-full-2026-07-05-run2.md)),
> preserved for comparison — see §8. Two regressions vs run 2 (`setup-dev-cluster`,
> `block-endpoint-default-role`), and a **large drop in recorded cost** driven by an
> omnis-side model/pricing change (§6).

## TL;DR

| Suite | Pass@1 | Rate | Cost | Wall |
|---|---|---:|---:|---:|
| **Main** | **23 / 24** | **95.8%** | $3.65 | 48m06s |
| **Gatekeeper** | **25 / 31** | **80.6%** | $2.40 | 92m38s |
| **Total** | **48 / 55** | **87.3%** | **$6.05** | **2h20m44s** |

omnis passed **23/24 main** and **25/31 gatekeeper**. Two tasks that passed in run 2 regressed:
`setup-dev-cluster` (main — incomplete per-user RBAC) and `block-endpoint-default-role`
(gatekeeper — audit under-report). The other 5 gatekeeper losses are the **same
audit-precision failures** seen in run 2. 0 errors, 0 setup aborts. `fix-oomkilled` is
disabled upstream, so 55 tasks were scored, not 56.

**Cost dropped ~5× vs run 2** ($29.29 → $6.05) even though the token volume was comparable.
This is an **omnis-side change, not a bench change**: the leader tier's effective price is now
~$0.66/M input (was ~$3.6/M), and **prompt caching is off** (`cache_read_tok = 0` everywhere;
it was 6.64M in run 2). The bench records whatever omnis's fleet reports.

---

## 1. Environment

| Component | Version / value |
|---|---|
| k8s-ai-bench | gke-labs/k8s-ai-bench @ `main` (`ac9ac9c`) |
| kind | shared cluster `k8s-ai-bench-eval` (main); per-task throwaway clusters (gatekeeper) |
| tooling | kubectl · helm · go (all on PATH) |
| squad | `kubernetes` (shipped), `bench-permissions.json` = `bypassPermissions` |
| model fleet | omnis's tiered fleet — **repriced/cheaper leader vs run 2, caching off** (see §6) |
| concurrency | **1 (sequential)** via the `CONCURRENCY` knob in `run.sh` |

## 2. Methodology

Two phases, back-to-back, **sequential**, into **separate output dirs** (`horizontal-pod-autoscaler`
exists in *both* suites, so a shared dir would clobber one):

- **Phase 1 — main / shared-cluster path** (`TASK_PATTERN='^[^g]'`, `.build/full-main`).
  One kind cluster (`k8s-ai-bench-eval`) + **one** multiplexed omnis-server on a random port;
  every task opens a session on it. 07:33:17Z → 08:21:23Z.
- **Phase 2 — gatekeeper / `isolation: cluster` path** (`TASKS_DIR=…/tasks/gatekeeper`,
  `.build/full-gatekeeper`). The harness creates a **dedicated throwaway cluster per task**;
  `omnis-agent` spawns a dedicated omnis-server for each (random port, own `OMNIS_HOME`),
  installs Gatekeeper/OPA, runs, tears down. 08:21:23Z → 09:54:01Z.

> **Why sequential.** The upstream harness treats `--concurrency 0` (its default) as
> *"auto = number of tasks"* — it runs **every task at once**, which on the shared
> single-cluster/single-server kind path causes contention + model-endpoint flooding → noisy
> pass/fail. `run.sh` defaults to `CONCURRENCY=1`.

**Clean teardown verified.** After the run: **no kind clusters remain** (`run.sh` deleted the
shared cluster; the harness + `omnis-agent` deleted each per-task gatekeeper cluster), both
shared servers were stopped, and no leftover temp `OMNIS_HOME` dirs. (One unrelated
omnis-server remains on the default port `:8080` — the interactive dev instance from
`~/Documents/Dev/omnis`; not a bench process, left untouched.)

## 3. Results — Main suite (23 / 24 = 95.8%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| create-canary-deployment | ✅ | 2m05s | $0.27 |
| create-network-policy | ✅ | 0m45s | $0.10 |
| create-pod | ✅ | 0m43s | $0.10 |
| create-pod-mount-configmaps | ✅ | 1m11s | $0.16 |
| create-pod-resources-limits | ✅ | 0m59s | $0.13 |
| create-simple-rbac | ✅ | 0m58s | $0.08 |
| debug-app-logs | ✅ | 1m59s | $0.04 |
| deployment-traffic-switch | ✅ | — | $0.07 |
| fix-crashloop | ✅ | 1m39s | $0.26 |
| fix-image-pull | ✅ | 1m09s | $0.08 |
| fix-pending-pod | ✅ | 2m42s | $0.07 |
| fix-probes | ✅ | 2m22s | $0.07 |
| fix-rbac-wrong-resource | ✅ | 2m15s | $0.12 |
| fix-service-routing | ✅ | 2m43s | $0.07 |
| fix-service-with-no-endpoints | ✅ | 2m39s | $0.31 |
| horizontal-pod-autoscaler | ✅ | 1m27s | $0.14 |
| list-images-for-pods | ✅ | 2m26s | $0.04 |
| multi-container-pod-communication | ✅ | 1m38s | $0.20 |
| resize-pvc | ✅ | 3m11s | $0.41 |
| rolling-update-deployment | ✅ | 2m15s | $0.09 |
| scale-deployment | ✅ | 1m11s | $0.08 |
| scale-down-deployment | ✅ | 0m48s | $0.07 |
| **setup-dev-cluster** | ❌ | 4m11s | $0.49 |
| statefulset-lifecycle | ✅ | 3m19s | $0.21 |

*\*Times are approximate — derived from consecutive `results.yaml` write times (includes each
task's setup + verify). The first task's delta is omitted (folds in cluster warm-up). Costs are
exact from `omnis-agent`'s per-task `est_cost_usd`.*

`debug-app-logs` passed cleanly — no fresh-cluster `default`-ServiceAccount race this run.

## 4. Results — Gatekeeper suite (25 / 31 = 80.6%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| allowed-ip | ✅ | 2m34s | $0.06 |
| allowed-repos | ✅ | — | $0.05 |
| allowed-reposv2 | ✅ | 9m51s | $0.06 |
| automount-serviceaccount-token | ✅ | 2m23s | $0.06 |
| **block-endpoint-default-role** | ❌ | 3m24s | $0.07 |
| block-loadbalancer-services | ✅ | 2m15s | $0.06 |
| block-wildcard-ingress | ✅ | 1m29s | $0.12 |
| container-cpu-requests-memory-limits-and-requests | ✅ | 3m50s | $0.06 |
| container-image-must-have-digest | ✅ | 1m41s | $0.10 |
| container-limits | ✅ | 2m59s | $0.08 |
| container-limits-and-requests | ✅ | 1m44s | $0.08 |
| **container-limits-ignore-cpu** | ❌ | 1m46s | $0.09 |
| container-requests | ✅ | 1m49s | $0.09 |
| **disallow-anonymous** | ❌ | 3m16s | $0.08 |
| disallow-interactive | ✅ | 2m42s | $0.06 |
| **disallowed-tags** | ❌ | 4m23s | $0.07 |
| ephemeral-storage-limit | ✅ | 4m10s | $0.07 |
| horizontal-pod-autoscaler | ✅ | 2m29s | $0.06 |
| memory-and-cpu-ratios | ✅ | 1m49s | $0.09 |
| memory-ratio-only | ✅ | 4m01s | $0.07 |
| must-have-key | ✅ | 1m45s | $0.09 |
| must-have-owner | ✅ | 2m28s | $0.08 |
| must-have-set-of-annotations | ✅ | 1m56s | $0.07 |
| **pod-disruption-budget** | ❌ | 4m14s | $0.19 |
| replica-limit | ✅ | 1m14s | $0.07 |
| repo-must-not-be-k8s-gcr-io | ✅ | 3m25s | $0.08 |
| **required-probes** | ❌ | 3m35s | $0.07 |
| tls-optional | ✅ | 2m33s | $0.06 |
| tls-required | ✅ | 2m32s | $0.06 |
| unique-ingress-host | ✅ | 3m31s | $0.08 |
| unique-service-selector | ✅ | 1m28s | $0.06 |

*\*Same caveat as §3; gatekeeper deltas also fold in the **next** task's cluster creation +
OPA install, so some (e.g. `allowed-reposv2` 9m51s) are inflated by downstream setup.*

## 5. Failure analysis (7 losses)

### 5.1 Main — `setup-dev-cluster` (regression vs run 2)

Not an audit task — a build task. `verify.sh` failed with:

```
All namespaces exist.
All developer ServiceAccounts exist.
Testing RBAC permissions...
FAIL: alice (User) cannot create pods in their own namespace 'dev-alice'
```

The agent created the namespaces and the developer ServiceAccounts, but the **per-developer
RBAC** that lets the *user* `alice` create pods in `dev-alice` was missing or wrong (likely
bound the ServiceAccount, or omitted the Role/RoleBinding for the `User` subject). This is a
**partial completion**, not an infra/permission failure (`error: ""`, ran to the deadline).
`setup-dev-cluster` passed in both 2026-07-05 runs, so it is a genuine regression this run — the
most expensive and most multi-step main task ($0.49, 5 namespaces × 3 SAs × RBAC).

### 5.2 Gatekeeper (6 losses)

Read-only audit tasks: the agent lists resources violating a policy, one `VIOLATING: <name>`
line each, scored by `expect` substrings (`contains`/`notContains`). Tasks seed **compliant
decoys** (catch over-reporting) and **subtle violations** (catch under-reporting).

| Task | Type | What happened |
|---|---|---|
| **block-endpoint-default-role** *(new)* | under-report | Grader wants `VIOLATING: system:aggregate-to-edit`. The two-pass audit instead flagged four built-in controller roles (`cluster-admin`, `system:controller:endpoint-controller`, `…generic-garbage-collector`, `…namespace-controller`) and **missed `system:aggregate-to-edit`** entirely. Over-focused on `system:controller:*` write-verb roles; missed the aggregation role that grants edit-on-endpoints. **Passed in run 2 → regression.** |
| **container-limits-ignore-cpu** | over-report | Correctly flagged `resource-002` but **also** flagged the compliant decoy `resource-001` (memory-limit boundary `≤` vs `<` misread). Same as run 2. |
| **disallowed-tags** | over-report | Found the real violations `resource-003…006` but also flagged the compliant decoy `resource-002`. Same as run 2. |
| **disallow-anonymous** | over-report / task-ambiguous | Flagged `resource-001` and `system:public-info-viewer` in addition to the intended `resource-002`. All bind `system:unauthenticated`; only `resource-002` also binds `system:anonymous`. Prompt says flag `anonymous` **or** `unauthenticated`, so the extra flags are *defensible per the wording*. Same as run 2. |
| **pod-disruption-budget** | naming mismatch | **Found the right violating PDB** but reported it by its real name `inventory-nginx-pdb-disallowed` instead of the grader's alias `resource-007`, so `contains: VIOLATING: resource-007` missed. Detection correct; identifier convention wrong. Same as run 2. |
| **required-probes** | under-report / task-ambiguous | Concluded all pods compliant, missing `resource-002` and `resource-003`. Read the policy as "≥1 probe anywhere"; grader wants stricter per-container readiness+liveness. Same as run 2. |

**Breakdown:** 3 over-reports · 2 under-reports · 1 naming mismatch. Five of six are **identical to
run 2**; the only new one is `block-endpoint-default-role`. None are execution/permission/infra
failures. `disallow-anonymous` and `required-probes` still hinge on **under-specified task
wording** and penalize a defensible reading.

## 6. Cost & token economics

| Metric | This run | Run 2 (2026-07-05) |
|---|---:|---:|
| Total cost | **$6.05** | $29.29 |
| — Main | $3.65 | $16.42 |
| — Gatekeeper | $2.40 | $12.87 |
| Prompt tokens | 11,775,606 | 13,437,563 |
| Output tokens | 178,908 | 232,979 |
| **Cache-read tokens** | **0** | 6,640,926 |

**Per-agent (whole run, main + gatekeeper):**

| Agent | Prompt tok | Output tok | Cache-read | Calls | ~Cost | Role |
|---|---:|---:|---:|---:|---:|---|
| k8s_leader | 8,902,009 | 80,307 | 0 | 560 | **~$5.91** | orchestrates; dominates cost (~98%) |
| k8s_investigator | 1,516,051 | 53,828 | 0 | 243 | ~$0.08 | read-only diagnosis (cheap tier) |
| k8s_auditor | 906,742 | 34,970 | 0 | 153 | ~$0.05 | gatekeeper policy audits (cheap tier; gatekeeper-only) |
| k8s_editor | 450,804 | 9,803 | 0 | 75 | ~$0.02 | mutations (cheap tier; main-only) |

- **The leader still dominates spend (~98%)** — it holds the premium tier and the bulk of prompt
  tokens; the worker agents doing the actual kubectl/audit work are 70–300× cheaper.
- **Two omnis-side changes vs run 2 explain the 5× cost drop.** (1) The **leader tier is
  repriced/cheaper**: backing the price out of the recorded cost (e.g. `must-have-key`: leader
  $0.0897 / 136,539 prompt tok) gives ~**$0.66/M input**, vs run 2's premium leader at ~$3.6/M —
  roughly a 5× reduction that outweighs everything else. (2) **Prompt caching is off** this run
  (`cache_read_tok = 0` everywhere; was 6.64M in run 2), which normally *raises* cost — so the
  price cut is doing all the work and then some.
- **These are fleet/config facts, not bench behaviour.** `omnis-agent` accepts `--model` but
  ignores it (omnis uses its own fleet); the cost column reflects whatever omnis's `models.json`
  prices at. Per the repo's standing gotcha, the effective per-tier price was **verified to have
  actually changed** (derived from cost ÷ tokens), so this is a real change, not a measurement
  artifact. Worth confirming intent on the omnis side — especially the caching regression, which
  the run-2 report had celebrated as newly landed.

## 7. Findings & recommendations

1. **Main-suite competence remains strong but no longer a clean sweep: 23/24.** The lone loss,
   `setup-dev-cluster`, is a multi-step RBAC build where the agent provisioned namespaces + SAs
   but left the per-*user* pod-create grant incomplete. Worth a targeted look at how the squad
   distinguishes `User` vs `ServiceAccount` subjects in RoleBindings — it's the one main task
   that flipped from pass to fail.
2. **Gatekeeper is flat-to-slightly-down (26→25).** `allowed-repos` and
   `automount-serviceaccount-token` (the run-2 wins) still pass, but `block-endpoint-default-role`
   regressed with an **under-report** (missed `system:aggregate-to-edit`, over-focused on
   `system:controller:*`). The audit playbook should **enumerate aggregation ClusterRoles**
   (`rbac.authorization.k8s.io/aggregate-to-*` labels), not just roles with explicit write verbs.
3. **The recurring 5 audit-precision losses are unchanged.** Same guidance as run 2: be **more
   conservative about flagging borderline/compliant decoys** (over-reports on
   `container-limits-ignore-cpu`, `disallowed-tags`), and report the grader's **`resource-NNN`
   alias, not the resource's own `metadata.name`** (cost `pod-disruption-budget` again).
4. **Confirm the omnis fleet/pricing change was intentional.** Cost fell 5× and **prompt caching
   is off** (0 cache-read vs 6.64M in run 2). Cheaper is good; a silent caching regression is
   not. Verify `models.json` pricing/tier and cache settings on the omnis side.
5. **File upstream task-clarity issues** for `disallow-anonymous` (`anonymous` OR `unauthenticated`
   wording vs grader wanting only the `anonymous` binding) and `required-probes` ("missing both"
   per-pod vs per-container scope). *(Strip any proprietary detail before filing.)*
6. **Infra & harness healthy.** Sequential execution, shared-server multiplexing (main), per-task
   dedicated servers + OPA installs + cluster teardowns (gatekeeper) all worked; no leftover
   clusters/processes; 0 setup aborts this run.

## 8. Comparison to the 2026-07-05 runs

| | Run 1 (07-05) | Run 2 (07-05) | This run (07-06) | Δ vs run 2 |
|---|---:|---:|---:|---:|
| Main | 24/24 (100%) | 24/24 (100%) | **23/24 (95.8%)** | **−1** |
| Gatekeeper | 24/31 (77.4%) | 26/31 (83.9%) | **25/31 (80.6%)** | **−1** |
| Total | 48/55 (87.3%) | 50/55 (90.9%) | **48/55 (87.3%)** | **−2** |
| Total cost | $21.41 | $29.29 | **$6.05** | **−$23.24 (~5× cheaper)** |
| Cache-read tok | 0 | 6,640,926 | **0** | caching off again |
| Wall | 1h39m | 2h02m | **2h21m** | +19m |

**Regressed to fail:** `setup-dev-cluster` (main, incomplete per-user RBAC),
`block-endpoint-default-role` (gatekeeper, missed `system:aggregate-to-edit`).
**Still failing (all three runs' core):** `container-limits-ignore-cpu`, `disallow-anonymous`,
`disallowed-tags`, `pod-disruption-budget`, `required-probes` — the audit-precision / task-clarity
set. **Still passing (run-2 wins held):** `allowed-repos`, `automount-serviceaccount-token`.

---

*Raw results (gitignored): `k8s-ai-bench/.build/full-main/<task>/` and
`.build/full-gatekeeper/<task>/` — each has `results.yaml`, `log.txt`, `trace.yaml` (trace/log
carry the per-agent usage footer).*
