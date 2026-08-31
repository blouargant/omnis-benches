# k8s-ai-bench — Full Run Report

**Date:** 2026-07-06 run 3 (run window 15:36:07Z → 17:56:58Z)
**Agent under test:** omnis (kubernetes squad, shipped unchanged, `bypassPermissions`)
**Scope:** Full suite — main (24 scored) + gatekeeper (31)
**Harness:** gke-labs/k8s-ai-bench @ `main` (`ac9ac9c`), `--concurrency 1` (sequential), kind ephemeral clusters

> Third full run on 2026-07-06, after the two earlier runs
> ([07-06 run 1](k8s-ai-bench-full-2026-07-06.md), [07-06 run 2](k8s-ai-bench-full-2026-07-06-run2.md))
> and the two 2026-07-05 runs
> ([run 1](k8s-ai-bench-full-2026-07-05.md), [run 2](k8s-ai-bench-full-2026-07-05-run2.md)).
> **The `omnis-server` binary was rebuilt at 15:28Z** (7 minutes before launch), *newer than* the
> 07-06 run-2 build (that run ended 14:00Z) — so this run again exercises a **different omnis build**.
> This one **recovers both of run 2's build-specific regressions** (§5, §8); treat as an
> omnis-side comparison, not a bench change.

## TL;DR

| Suite | Pass@1 | Rate | Cost | Wall |
|---|---|---:|---:|---:|
| **Main** | **21 / 24** | **87.5%** | $4.24 | 55m17s |
| **Gatekeeper** | **26 / 31** | **83.9%** | $2.13¹ | 1h24m50s |
| **Total** | **47 / 55** | **85.5%** | **$6.37¹** | **2h20m51s** |

¹ Gatekeeper/total cost **excludes 1 task** (`pod-disruption-budget`) that **hit its own 5-minute
`task.yaml` timeout** and was hard-killed by the harness before `omnis-agent` could print its usage
footer — so its spend is unaccounted (true total is marginally higher). The same hard-kill
**orphaned its spawned omnis-server** (§9, reaped post-run).

omnis passed **21/24 main** and **26/31 gatekeeper**. Net **+2 vs 07-06 run 2** (45→47), driven by
**two recoveries and no new regressions**: `allowed-reposv2` (was a 5m timeout → now passes) and
`unique-service-selector` (was a degenerate one-shot output → now passes). Both were run-2
regressions tied to that build; the newer 15:28Z build clears them. The remaining **8 losses are all
persistent** (identical tasks/causes to prior runs). 0 harness/infra setup aborts.

**Cost is flat** ($6.28 → $6.37) — same cheap-leader / **caching-off** regime
(`cache_read_tok = 0` everywhere); no pricing change this run.

---

## 1. Environment

| Component | Version / value |
|---|---|
| k8s-ai-bench | gke-labs/k8s-ai-bench @ `main` (`ac9ac9c`) — same commit as 07-06 runs 1 & 2 |
| omnis-server | **rebuilt 15:28Z (`/usr/bin/omnis-server`, 41 MB)** — newer than 07-06 run 2 |
| kind | 0.32.0 · shared cluster `k8s-ai-bench-eval` (main); per-task throwaway clusters (gatekeeper) |
| tooling | docker · kubectl · helm · go (all on PATH) |
| squad | `kubernetes` (shipped), `bench-permissions.json` = `bypassPermissions` |
| model fleet | omnis's tiered fleet — premium leader, **caching off** (unchanged); `k8s_cleaner` agent present (introduced with the run-2 build) |
| concurrency | **1 (sequential)** via the `CONCURRENCY` knob in `run.sh` |

## 2. Methodology

Two phases, back-to-back, **sequential**, into **separate, fresh output dirs**
(`full-main-run3` / `full-gatekeeper-run3`) so prior raw data was preserved and
`horizontal-pod-autoscaler` — which exists in *both* suites — could not clobber itself:

- **Phase 1 — main / shared-cluster path** (`TASK_PATTERN='^[^g]'`, `.build/full-main-run3`).
  One kind cluster (`k8s-ai-bench-eval`) + **one** multiplexed omnis-server on a random port; every
  task opens a session on it. 15:36:07Z → 16:31:48Z (harness eval 55m17s).
- **Phase 2 — gatekeeper / `isolation: cluster` path** (`TASKS_DIR=…/tasks/gatekeeper`,
  `.build/full-gatekeeper-run3`). The harness creates a **dedicated throwaway cluster per task**;
  `omnis-agent` spawns a dedicated omnis-server for each (random port, own `OMNIS_HOME`), installs
  Gatekeeper/OPA, runs, tears down. 16:31:48Z → 17:56:58Z (harness eval 1h24m50s).

`fix-oomkilled` is disabled upstream (skipped), so **55 tasks were scored**, not 56.

> **Why sequential.** The upstream harness treats `--concurrency 0` (its default) as
> *"auto = number of tasks"* — it runs **every task at once**, which on the shared
> single-cluster/single-server kind path causes contention + model-endpoint flooding → noisy
> pass/fail. `run.sh` defaults to `CONCURRENCY=1`.

**Teardown.** After the run: **no kind clusters remained** (`run.sh` deleted the shared cluster; the
harness + `omnis-agent` deleted each per-task gatekeeper cluster), both phase shared servers were
stopped. **One per-task gatekeeper server leaked** (`pod-disruption-budget`, hard-killed at its 5m
timeout) — see §9; reaped by hand post-run. (The unrelated omnis-server on default port `:8080` is
the interactive dev instance; not a bench process, left untouched.)

## 3. Results — Main suite (21 / 24 = 87.5%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| create-canary-deployment | ✅ | — | $0.27 |
| **create-network-policy** | ❌ | 0m44s | $0.06 |
| **create-pod** | ❌ | 0m59s | $0.10 |
| create-pod-mount-configmaps | ✅ | 1m06s | $0.08 |
| create-pod-resources-limits | ✅ | 0m56s | $0.12 |
| create-simple-rbac | ✅ | 0m43s | $0.09 |
| debug-app-logs | ✅ | 2m16s | $0.04 |
| deployment-traffic-switch | ✅ | 2m16s | $0.21 |
| fix-crashloop | ✅ | 1m56s | $0.13 |
| fix-image-pull | ✅ | 1m34s | $0.13 |
| fix-pending-pod | ✅ | 1m28s | $0.21 |
| fix-probes | ✅ | 2m59s | $0.09 |
| fix-rbac-wrong-resource | ✅ | 0m49s | $0.13 |
| fix-service-routing | ✅ | 3m05s | $0.08 |
| fix-service-with-no-endpoints | ✅ | 2m26s | $0.25 |
| horizontal-pod-autoscaler | ✅ | 2m02s | $0.16 |
| list-images-for-pods | ✅ | 2m16s | $0.04 |
| multi-container-pod-communication | ✅ | 1m44s | $0.18 |
| resize-pvc | ✅ | 5m58s | $0.42 |
| rolling-update-deployment | ✅ | 2m32s | $0.07 |
| scale-deployment | ✅ | 0m58s | $0.12 |
| scale-down-deployment | ✅ | 0m51s | $0.09 |
| **setup-dev-cluster** | ❌ | 7m55s | $0.96 |
| statefulset-lifecycle | ✅ | 5m28s | $0.22 |

*\*Times are approximate — derived from consecutive `results.yaml` write times (includes each
task's setup + verify). The first-completing task's delta is omitted (folds in cluster warm-up).
Costs are exact from `omnis-agent`'s per-task `est_cost_usd`.*

## 4. Results — Gatekeeper suite (26 / 31 = 83.9%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| allowed-ip | ✅ | 1m04s | $0.06 |
| allowed-repos | ✅ | 6m22s | $0.06 |
| **allowed-reposv2** *(recovered)* | ✅ | 6m07s | $0.07 |
| automount-serviceaccount-token | ✅ | 2m23s | $0.06 |
| block-endpoint-default-role | ✅ | 3m21s | $0.07 |
| block-loadbalancer-services | ✅ | 1m45s | $0.06 |
| block-wildcard-ingress | ✅ | 1m11s | $0.07 |
| container-cpu-requests-memory-limits-and-requests | ✅ | 3m07s | $0.06 |
| container-image-must-have-digest | ✅ | 2m44s | $0.07 |
| container-limits | ✅ | 2m32s | $0.07 |
| container-limits-and-requests | ✅ | 1m14s | $0.06 |
| **container-limits-ignore-cpu** | ❌ | 1m15s | $0.07 |
| container-requests | ✅ | 2m47s | $0.07 |
| **disallow-anonymous** | ❌ | 2m21s | $0.08 |
| disallow-interactive | ✅ | 2m22s | $0.06 |
| **disallowed-tags** | ❌ | 5m06s | $0.07 |
| ephemeral-storage-limit | ✅ | 3m53s | $0.07 |
| horizontal-pod-autoscaler | ✅ | 1m32s | $0.13 |
| memory-and-cpu-ratios | ✅ | 2m50s | $0.07 |
| memory-ratio-only | ✅ | 3m49s | $0.08 |
| must-have-key | ✅ | 1m58s | $0.06 |
| must-have-owner | ✅ | 1m02s | $0.06 |
| must-have-set-of-annotations | ✅ | — | $0.07 |
| **pod-disruption-budget** | ❌ timeout | 5m12s | — (no footer) |
| replica-limit | ✅ | 2m10s | $0.06 |
| repo-must-not-be-k8s-gcr-io | ✅ | 2m51s | $0.07 |
| **required-probes** | ❌ | 3m14s | $0.07 |
| tls-optional | ✅ | 2m07s | $0.06 |
| tls-required | ✅ | 1m53s | $0.09 |
| unique-ingress-host | ✅ | 1m48s | $0.12 |
| **unique-service-selector** *(recovered)* | ✅ | 1m09s | $0.07 |

*\*Same caveat as §3; gatekeeper deltas also fold in the **next** task's cluster creation + OPA
install (so they're inflated — e.g. `allowed-reposv2` passed well under its 5m budget; the 6m07s is
downstream setup). `pod-disruption-budget`'s delta reflects the harness's hard 5m00s cutoff.*

## 5. Failure analysis (8 losses)

### 5.1 Main (3 losses — all persistent)

| Task | Type | What happened |
|---|---|---|
| **create-pod** *(persistent)* | wrong image | Created the `web-server` pod + namespace, pod `Running 1/1`, but used image **`nginx:latest`**; `verify.sh` rejects it (`Pod is using incorrect image: nginx:latest`). Ran clean (`error: ""`). **Identical to 07-06 run 2** — the wrong image-tag choice persists on this build. |
| **create-network-policy** *(persistent)* | egress spec mismatch | Built the NetworkPolicy but the **egress spec shape doesn't match** after normalization (`Failed: NetworkPolicy egress specs don't match`). The grader's expected policy scopes the DNS egress rule to kube-dns pods (`to: [{namespaceSelector: {}, podSelector: {matchLabels: {k8s-app: kube-dns}}}]`); the agent left the DNS rule unscoped. Ran clean. **Same as 07-06 run 2.** |
| **setup-dev-cluster** *(persistent)* | partial RBAC | `FAIL: alice (User) cannot create pods in their own namespace 'dev-alice'`. Namespaces + developer ServiceAccounts created, but the per-**user** pod-create RBAC (Role/RoleBinding for the `User` subject) is still missing/wrong. **Same multi-step RBAC gap as runs 1 & 2** — but this run it burned **$0.96 / 7m55s** (vs $0.35 in run 2) chasing it and still failed (§6). |

### 5.2 Gatekeeper (5 losses — all persistent)

Read-only audit tasks: the agent lists policy-violating resources, one `VIOLATING: <name>` line each,
scored by `expect` substrings (`contains`/`notContains`). Tasks seed **compliant decoys** (catch
over-reporting) and **subtle violations** (catch under-reporting).

| Task | Type | What happened |
|---|---|---|
| **container-limits-ignore-cpu** *(persistent)* | over-report | Flagged both `resource-001` (memory limit `1Gi`) and `resource-002` (`2Gi`). The agent read the policy as memory `< 1Gi`, so it flagged the **compliant boundary decoy `resource-001`** (`1Gi` is `≤`, allowed) → `notContains` tripped. **Same `≤` vs `<` misread as prior runs.** |
| **disallow-anonymous** *(persistent, task-ambiguous)* | over-report | Flagged `resource-001`, `resource-002`, **and `system:public-info-viewer`** (binds `system:unauthenticated`). Prompt says flag `anonymous` **or** `unauthenticated`, so this is defensible per the wording. **Same as prior runs.** |
| **disallowed-tags** *(persistent)* | over-report | Flagged `resource-002`–`resource-006` (5 pods); one is a **compliant decoy** the grader's `notContains` rejects (`resource-004`'s image `openpolicyagent:443/opa` — the `:443` is a registry port, not a missing tag — was misread as untagged). **Same over-report pattern as prior runs.** |
| **required-probes** *(persistent, task-ambiguous)* | under-report | Concluded **0 violations** — read the rule as "a pod is compliant if *any* container has *any* probe". The grader wants stricter per-container scope and expects `VIOLATING: resource-003` (`contains` miss). **Same under-report as prior runs.** |
| **pod-disruption-budget** *(persistent — timeout)* | **timeout** | `task timed out after 5m0s` (task's own `timeout: 5m`; harness default is 10m). The session actually **finished the stream at ~4m53s from session start**, but `omnis-agent`'s total wall (child-server spawn + OPA install + the audit) tipped just over 5m, so the harness SIGKILLed it right at the boundary → no usage footer, **leaked server (§9)**. Also timed out in run 2. |

**Breakdown:** 3 over-reports · 1 under-report · 1 timeout — **all 5 are identical tasks/causes to
prior runs.** No new gatekeeper failures this run.

**Recovered vs 07-06 run 2 (both were run-2 regressions):**
- **`allowed-reposv2`** — run 2 hit its 5m timeout mid–second-audit-pass; this run it **finishes under
  budget and passes**.
- **`unique-service-selector`** — run 2 emitted the bare token `list_skills` as prose and stopped
  after one degenerate call; this run it **runs a real audit and passes** ($0.07, normal token
  volume — not the $0.008 one-shot).

Both recoveries align with the newer 15:28Z build — the two run-2 regressions looked build-specific
(a slow second-pass and a tool-call serialization glitch), and both are gone here.

## 6. Cost & token economics

| Metric | This run (07-06 run 3) | 07-06 run 2 |
|---|---:|---:|
| Total cost | **$6.37**¹ | $6.28¹ |
| — Main | $4.24 | $4.18 |
| — Gatekeeper | $2.13¹ | $2.10¹ |
| Prompt tokens | 12,077,372¹ | 12,817,966¹ |
| Output tokens | 177,206¹ | 198,316¹ |
| **Cache-read tokens** | **0** | 0 |

¹ Excludes `pod-disruption-budget` (killed at its 5m timeout → no usage footer emitted). Its
spend/tokens are unaccounted; true totals are marginally higher. (Run 2 excluded 2 such tasks.)

**Per-agent (whole run, main + gatekeeper):**

| Agent | Prompt tok | Output tok | Cache-read | Calls | ~Cost | Role |
|---|---:|---:|---:|---:|---:|---|
| k8s_leader | 9,426,914 | 78,319 | 0 | 567 | **~$6.24** | orchestrates; dominates cost (~98%) |
| k8s_investigator | 1,313,942 | 50,801 | 0 | 210 | ~$0.07 | read-only diagnosis (cheap tier) |
| k8s_auditor | 1,113,483 | 42,992 | 0 | 177 | ~$0.06 | gatekeeper policy audits (cheap tier) |
| k8s_editor | 201,631 | 4,231 | 0 | 33 | ~$0.01 | mutations (cheap tier; main-only) |
| k8s_cleaner | 21,402 | 863 | 0 | 5 | ~$0.00 | teardown/cleanup helper |

- **Cost regime unchanged.** The leader still holds the premium tier and ~98% of spend (~$6.24 of
  $6.37); backing price out of the leader tally gives ~**$0.66/M input** — same as prior runs.
  **Prompt caching is still off** (`cache_read_tok = 0` everywhere) — no change, still worth
  confirming intent on the omnis side.
- **`setup-dev-cluster` is the cost outlier.** It alone cost **$0.96** (23% of the *entire* main
  phase) over 7m55s and still failed — the agent iterated hard on the per-user RBAC without solving
  it. Run 2 spent $0.35 on the same failure. A targeted fix would both recover the pass and cut cost.
- **`k8s_editor` activity dropped** (33 calls / $0.01 vs 80 calls / $0.03 in run 2) — fewer mutation
  round-trips this run; a behaviour shift on the new build, not a scoring change.

## 7. Findings & recommendations

1. **Net +2 and the failure shape improved.** Both of run 2's build-specific regressions recovered
   (`allowed-reposv2` timeout, `unique-service-selector` degenerate output) and **no new regressions
   appeared**. The `unique-service-selector` tool-call serialization glitch flagged in run 2 (§7.2
   there) did **not** reproduce on this build — good signal that it was transient/build-specific, but
   worth keeping an eye on across future builds.
2. **The 8 remaining losses are the stable persistent core.** Main: `create-pod` (wrong image tag),
   `create-network-policy` (unscoped DNS egress rule), `setup-dev-cluster` (per-user `User`-subject
   RBAC). Gatekeeper: `container-limits-ignore-cpu` (`≤`/`<` boundary over-report), `disallowed-tags`
   (registry-port-as-tag over-report), `disallow-anonymous` + `required-probes` (task-ambiguous),
   `pod-disruption-budget` (5m timeout). None are noise now — each is reproducible and individually
   fixable.
3. **`pod-disruption-budget` misses the 5m budget by seconds.** The stream completed at ~4m53s but
   `omnis-agent`'s total wall (child-server spawn + OPA install + audit) tipped over 5m. Unlike run 2
   (where it never finished), this run it was *right at the line* — shaving the child-server
   startup/OPA-install overhead, or tightening the two-pass audit to a single pass on the
   strictest-timeout tasks, would likely recover it.
4. **`omnis-agent` still leaks its spawned server on a task-timeout hard-kill (bug).** One leak this
   run (`pod-disruption-budget`, §9) — down from 2 in run 2 only because `allowed-reposv2` recovered.
   Same root cause: the harness SIGKILLs `omnis-agent` at the task's 5m timeout **before** its own
   600s deadline + cleanup path, orphaning the dedicated per-task server + its `/tmp/omnis-kab-*`
   home. Fixes unchanged: (a) `omnis-agent` starts the child server in its **own process group** +
   installs a SIGTERM/SIGINT handler that kills it; and/or (b) `run.sh`'s `cleanup()` **sweeps
   leftover `omnis-kab-*` servers/dirs** at end-of-run. **No Pass@k impact** (each task has its own
   cluster/port; the harness scored stdout before the kill) but zombies accumulate across runs.
5. **`setup-dev-cluster` is now both a persistent fail and a cost sink** ($0.96, 7m55s). Same
   `User`-subject Role/RoleBinding gap as runs 1 & 2 — a targeted squad/prompt fix would recover a
   pass *and* the biggest single-task spend in the main phase.
6. **Recurring audit-precision losses unchanged (4).** Be **more conservative about compliant
   decoys** (`container-limits-ignore-cpu` `≤`-boundary, `disallowed-tags` registry-port), and the
   two task-clarity cases (`disallow-anonymous`, `required-probes`) still penalize a defensible
   reading — worth filing upstream (strip proprietary detail first).
7. **Cost/caching unchanged.** Spend flat at $6.37 (~98% leader), caching still off, ~$0.66/M leader.

## 8. Comparison to prior runs

| | Run 1 (07-05) | Run 2 (07-05) | Run 1 (07-06) | Run 2 (07-06) | **This run (07-06 r3)** | Δ vs 07-06 r2 |
|---|---:|---:|---:|---:|---:|---:|
| Main | 24/24 (100%) | 24/24 (100%) | 23/24 (95.8%) | 21/24 (87.5%) | **21/24 (87.5%)** | **0** |
| Gatekeeper | 24/31 (77.4%) | 26/31 (83.9%) | 25/31 (80.6%) | 24/31 (77.4%) | **26/31 (83.9%)** | **+2** |
| Total | 48/55 (87.3%) | 50/55 (90.9%) | 48/55 (87.3%) | 45/55 (81.8%) | **47/55 (85.5%)** | **+2** |
| Total cost | $21.41 | $29.29 | $6.05 | $6.28 | **$6.37** | +$0.09 |
| Cache-read tok | 0 | 6,640,926 | 0 | 0 | **0** | — |
| Wall | 1h39m | 2h02m | 2h21m | 2h43m | **2h21m** | −22m |

**Recovered (vs 07-06 r2):** `allowed-reposv2` (5m timeout → pass), `unique-service-selector`
(degenerate output → pass).
**Regressed to fail:** none.
**Still failing (persistent core):** `create-pod`, `create-network-policy`, `setup-dev-cluster`
(main); `container-limits-ignore-cpu`, `disallow-anonymous`, `disallowed-tags`, `required-probes`,
`pod-disruption-budget` (gatekeeper).

## 9. Teardown / server-leak note

Post-run state was clean **except** one orphaned per-task gatekeeper omnis-server:

| PID | Task | Port | `OMNIS_HOME` | Cause |
|---|---|---|---|---|
| 3329011 | `pod-disruption-budget` | :56747 | `/tmp/omnis-kab-67xfi2ch` | hard-killed at 5m timeout |

**Reparented to systemd** (its `omnis-agent` parent died), bound to the now-deleted task kubeconfig →
harmless zombie. **Reaped by hand** (`kill` + `rm -rf` its temp home); the dev `:8080` instance was
left untouched; no kind clusters remained; no other `/tmp/omnis-kab-*` homes survived. Root cause +
fix in §7.4. **No impact on Pass@k** — the task used its own cluster/server/port, so no
cross-contamination, and the harness scored its answer before the kill.

---

*Raw results (gitignored): `k8s-ai-bench/.build/full-main-run3/<task>/` and
`.build/full-gatekeeper-run3/<task>/` — each has `results.yaml`, `log.txt`, `trace.yaml`
(`log.txt` carries the per-agent `omnis-agent: usage …` footer, absent for the 1 timed-out task).
Run logs: `.build/logs-2026-07-06-run3/`.*
