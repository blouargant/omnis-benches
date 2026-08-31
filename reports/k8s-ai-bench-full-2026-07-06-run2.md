# k8s-ai-bench — Full Run Report

**Date:** 2026-07-06 run 2 (run window 11:17:24Z → 14:00:18Z)
**Agent under test:** omnis (kubernetes squad, shipped unchanged, `bypassPermissions`)
**Scope:** Full suite — main (24 scored) + gatekeeper (31)
**Harness:** gke-labs/k8s-ai-bench @ `main` (`ac9ac9c`), `--concurrency 1` (sequential), kind ephemeral clusters

> Second full run on 2026-07-06, after the morning run
> ([07-06 run 1](k8s-ai-bench-full-2026-07-06.md)) and the two 2026-07-05 runs
> ([run 1](k8s-ai-bench-full-2026-07-05.md), [run 2](k8s-ai-bench-full-2026-07-05-run2.md)).
> **The `omnis-server` binary was rebuilt at 13:07 the previous day / same-day** (newer than
> the 07-06 run-1 window, which ended 09:54Z), so this run exercises a **different omnis build**.
> That shows up as several new agent-behaviour regressions (§5) — treat this as an
> omnis-side comparison, not a bench change.

## TL;DR

| Suite | Pass@1 | Rate | Cost | Wall |
|---|---|---:|---:|---:|
| **Main** | **21 / 24** | **87.5%** | $4.18 | 54m17s |
| **Gatekeeper** | **24 / 31** | **77.4%** | $2.10¹ | 1h48m37s |
| **Total** | **45 / 55** | **81.8%** | **$6.28¹** | **2h42m54s** |

¹ Gatekeeper/total cost **excludes 2 tasks** (`allowed-reposv2`, `pod-disruption-budget`) that
**hit their own 5-minute `task.yaml` timeout** and were hard-killed by the harness before
`omnis-agent` could print its usage footer — so their spend is unaccounted (true total is
marginally higher). The same hard-kill **orphaned their spawned omnis-servers** (§9).

omnis passed **21/24 main** and **24/31 gatekeeper**. Net **−3 vs 07-06 run 1** (48→45).
**Four regressions** (`create-pod`, `create-network-policy`, `allowed-reposv2`,
`unique-service-selector`), **one recovery** (`block-endpoint-default-role`). The failure mix
changed shape: 2 new **timeouts** and 1 **degenerate one-shot output** appeared this run,
on top of the recurring audit-precision losses. 0 harness/infra setup aborts.

**Cost is flat vs 07-06 run 1** ($6.05 → $6.28) — same cheap-leader / **caching-off** regime
(`cache_read_tok = 0` everywhere); no pricing change this run.

---

## 1. Environment

| Component | Version / value |
|---|---|
| k8s-ai-bench | gke-labs/k8s-ai-bench @ `main` (`ac9ac9c`) — same commit as 07-06 run 1 |
| omnis-server | **rebuilt 13:07 (`/usr/bin/omnis-server`, 41 MB)** — newer than 07-06 run 1 |
| kind | 0.32.0 · shared cluster `k8s-ai-bench-eval` (main); per-task throwaway clusters (gatekeeper) |
| tooling | docker 29.1.3 · kubectl · helm · go 1.26.0 (all on PATH) |
| squad | `kubernetes` (shipped), `bench-permissions.json` = `bypassPermissions` |
| model fleet | omnis's tiered fleet — cheap leader, **caching off** (unchanged vs 07-06 run 1); **new `k8s_cleaner` agent** appears (§7) |
| concurrency | **1 (sequential)** via the `CONCURRENCY` knob in `run.sh` |

## 2. Methodology

Two phases, back-to-back, **sequential**, into **separate, fresh output dirs**
(`full-main-run2` / `full-gatekeeper-run2`) so the 07-06 run-1 raw data was preserved and
`horizontal-pod-autoscaler` — which exists in *both* suites — could not clobber itself:

- **Phase 1 — main / shared-cluster path** (`TASK_PATTERN='^[^g]'`, `.build/full-main-run2`).
  One kind cluster (`k8s-ai-bench-eval`) + **one** multiplexed omnis-server on a random port
  (`:45101`); every task opens a session on it. 11:17:24Z → 12:11:41Z.
- **Phase 2 — gatekeeper / `isolation: cluster` path** (`TASKS_DIR=…/tasks/gatekeeper`,
  `.build/full-gatekeeper-run2`). The harness creates a **dedicated throwaway cluster per task**;
  `omnis-agent` spawns a dedicated omnis-server for each (random port, own `OMNIS_HOME`),
  installs Gatekeeper/OPA, runs, tears down. 12:11:41Z → 14:00:18Z.

`fix-oomkilled` is disabled upstream (skipped), so **55 tasks were scored**, not 56.

> **Why sequential.** The upstream harness treats `--concurrency 0` (its default) as
> *"auto = number of tasks"* — it runs **every task at once**, which on the shared
> single-cluster/single-server kind path causes contention + model-endpoint flooding → noisy
> pass/fail. `run.sh` defaults to `CONCURRENCY=1`.

**Teardown.** After the run: **no kind clusters remained** (`run.sh` deleted the shared cluster;
the harness + `omnis-agent` deleted each per-task gatekeeper cluster), the main-phase shared
server (pid 2299969) and gatekeeper shared server were stopped. **But two per-task gatekeeper
servers leaked** — see §9; both were reaped by hand post-run. (One unrelated omnis-server remains
on the default port `:8080` — the interactive dev instance; not a bench process, left untouched.)

## 3. Results — Main suite (21 / 24 = 87.5%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| create-canary-deployment | ✅ | 2m11s | $0.14 |
| **create-network-policy** | ❌ | 0m58s | $0.11 |
| **create-pod** | ❌ | 0m55s | $0.04 |
| create-pod-mount-configmaps | ✅ | 1m12s | $0.10 |
| create-pod-resources-limits | ✅ | 1m06s | $0.13 |
| create-simple-rbac | ✅ | 1m08s | $0.19 |
| debug-app-logs | ✅ | 1m40s | $0.05 |
| deployment-traffic-switch | ✅ | 3m21s | $0.08 |
| fix-crashloop | ✅ | 2m01s | $0.22 |
| fix-image-pull | ✅ | 1m59s | $0.18 |
| fix-pending-pod | ✅ | 2m37s | $0.09 |
| fix-probes | ✅ | 3m09s | $0.09 |
| fix-rbac-wrong-resource | ✅ | — | $0.14 |
| fix-service-routing | ✅ | 2m33s | $0.17 |
| fix-service-with-no-endpoints | ✅ | 3m02s | $0.11 |
| horizontal-pod-autoscaler | ✅ | 1m48s | $0.12 |
| list-images-for-pods | ✅ | 2m17s | $0.04 |
| multi-container-pod-communication | ✅ | 4m19s | $0.36 |
| resize-pvc | ✅ | 4m22s | $0.77 |
| rolling-update-deployment | ✅ | 1m42s | $0.16 |
| scale-deployment | ✅ | 0m48s | $0.12 |
| scale-down-deployment | ✅ | 0m53s | $0.11 |
| **setup-dev-cluster** | ❌ | 4m06s | $0.35 |
| statefulset-lifecycle | ✅ | 4m28s | $0.31 |

*\*Times are approximate — derived from consecutive `results.yaml` write times (includes each
task's setup + verify). The first-completing task's delta is omitted (folds in cluster warm-up).
Costs are exact from `omnis-agent`'s per-task `est_cost_usd`.*

## 4. Results — Gatekeeper suite (24 / 31 = 77.4%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| allowed-ip | ✅ | 2m45s | $0.06 |
| allowed-repos | ✅ | 4m44s | $0.06 |
| **allowed-reposv2** | ❌ timeout | 5m00s | — (no footer) |
| automount-serviceaccount-token | ✅ | 2m35s | $0.08 |
| block-endpoint-default-role | ✅ | 3m56s | $0.06 |
| block-loadbalancer-services | ✅ | 1m20s | $0.06 |
| block-wildcard-ingress | ✅ | 3m18s | $0.07 |
| container-cpu-requests-memory-limits-and-requests | ✅ | 3m11s | $0.07 |
| container-image-must-have-digest | ✅ | 3m11s | $0.06 |
| container-limits | ✅ | 4m09s | $0.07 |
| container-limits-and-requests | ✅ | 2m07s | $0.10 |
| **container-limits-ignore-cpu** | ❌ | 3m23s | $0.07 |
| container-requests | ✅ | 3m10s | $0.07 |
| **disallow-anonymous** | ❌ | 3m08s | $0.07 |
| disallow-interactive | ✅ | 4m55s | $0.07 |
| **disallowed-tags** | ❌ | 5m04s | $0.07 |
| ephemeral-storage-limit | ✅ | 4m29s | $0.07 |
| horizontal-pod-autoscaler | ✅ | 3m15s | $0.07 |
| memory-and-cpu-ratios | ✅ | 4m05s | $0.08 |
| memory-ratio-only | ✅ | 3m58s | $0.07 |
| must-have-key | ✅ | 2m35s | $0.07 |
| must-have-owner | ✅ | 2m49s | $0.07 |
| must-have-set-of-annotations | ✅ | 2m31s | $0.06 |
| **pod-disruption-budget** | ❌ timeout | 5m00s | — (no footer) |
| replica-limit | ✅ | 2m10s | $0.07 |
| repo-must-not-be-k8s-gcr-io | ✅ | 3m18s | $0.07 |
| **required-probes** | ❌ | 3m02s | $0.19 |
| tls-optional | ✅ | — | $0.08 |
| tls-required | ✅ | 3m07s | $0.07 |
| unique-ingress-host | ✅ | 3m42s | $0.10 |
| **unique-service-selector** | ❌ degenerate | 0m48s | $0.01 |

*\*Same caveat as §3; gatekeeper deltas also fold in the **next** task's cluster creation + OPA
install. The two timeouts show the harness's hard **5m00s** cutoff (their `results.yaml` mtime
deltas are inflated by downstream setup and are not shown).*

## 5. Failure analysis (10 losses)

### 5.1 Main (3 losses)

| Task | Type | What happened |
|---|---|---|
| **create-pod** *(regression)* | wrong image | Created the `web-server` pod and namespace, pod `Running 1/1`, but used image **`nginx:latest`**; `verify.sh` rejects it (`Pod is using incorrect image: nginx:latest`). Ran clean (`error: ""`). Passed every prior run — the agent's image-tag choice changed under the new build. |
| **create-network-policy** *(regression)* | spec mismatch | Built a NetworkPolicy `np` in `ns1` (egress-only), but the **egress spec shape doesn't match** after normalization — the grader's expected policy carries a `to: [{namespaceSelector: {}}]` DNS rule the agent structured differently (`Failed: NetworkPolicy egress specs don't match`). Ran clean. Passed last run. |
| **setup-dev-cluster** *(persistent)* | partial RBAC | `FAIL: alice (User) cannot create pods in their own namespace 'dev-alice'`. Namespaces + developer ServiceAccounts created, but the per-**user** pod-create RBAC (Role/RoleBinding for the `User` subject) is still missing/wrong. **Identical to 07-06 run 1** — same multi-step RBAC gap. |

### 5.2 Gatekeeper (7 losses)

Read-only audit tasks: the agent lists policy-violating resources, one `VIOLATING: <name>` line
each, scored by `expect` substrings (`contains`/`notContains`). Tasks seed **compliant decoys**
(catch over-reporting) and **subtle violations** (catch under-reporting).

| Task | Type | What happened |
|---|---|---|
| **allowed-reposv2** *(regression — NEW mode)* | **timeout** | `task timed out after 5m0s` (the task's own `task.yaml` `timeout: 5m`). The agent completed a first audit pass, then started an **independent second verification pass** with `k8s_auditor` and was hard-killed at 5m before finishing. Passed last run (finished under 5m); the extra pass pushed it over budget. → **leaked server, §9.** |
| **container-limits-ignore-cpu** *(persistent)* | over-report | Flagged the **compliant decoy `resource-001`** (`notContains` tripped). Memory-limit boundary `≤` vs `<` misread. Same as prior runs. |
| **disallow-anonymous** *(persistent, task-ambiguous)* | over-report | Flagged `resource-001` (binds `system:unauthenticated` only) in addition to the intended anonymous binding. Prompt says flag `anonymous` **or** `unauthenticated`, so this is defensible per the wording. Same as prior runs. |
| **disallowed-tags** *(persistent)* | over-report | Flagged the **compliant decoy `resource-002`** alongside the real violations. Same as prior runs. |
| **pod-disruption-budget** *(persistent — NEW mode)* | **timeout** | `task timed out after 5m0s` (task's own `timeout: 5m`). Last run this failed on a naming mismatch (reported the PDB's real name instead of the grader's `resource-007` alias); **this run it never finished** — hard-killed at 5m. → **leaked server, §9.** |
| **required-probes** *(persistent, task-ambiguous)* | under-report | Missed `resource-003` (`contains: VIOLATING: resource-003` did not match). Read the policy as "≥1 probe anywhere"; grader wants stricter per-container scope. Same as prior runs. |
| **unique-service-selector** *(regression — degenerate)* | **broken output** | The leader made **one** model call ($0.008, 146 output tokens) that emitted the literal text `list_skills` — a tool *name* rendered as prose, not an invocation — then the turn ended with **no audit performed**. The harness scored the raw string `"\n\nlist_skills\n"`; `VIOLATING: resource-002` never appeared. A **tool-call formatting glitch**, not an audit-precision miss. Passed last run. |

**Breakdown:** 2 timeouts · 1 degenerate output · 3 over-reports · 1 under-report. The three
over-reports + one under-report are **identical to prior runs**; the two timeouts and the
degenerate output are **new this run** and align with the rebuilt omnis binary.

**Recovered vs 07-06 run 1:** `block-endpoint-default-role` — last run it under-reported (missed
`system:aggregate-to-edit`); this run it **passes**.

## 6. Cost & token economics

| Metric | This run (07-06 run 2) | 07-06 run 1 |
|---|---:|---:|
| Total cost | **$6.28**¹ | $6.05 |
| — Main | $4.18 | $3.65 |
| — Gatekeeper | $2.10¹ | $2.40 |
| Prompt tokens | 12,817,966¹ | 11,775,606 |
| Output tokens | 198,316¹ | 178,908 |
| **Cache-read tokens** | **0** | 0 |

¹ Excludes `allowed-reposv2` + `pod-disruption-budget` (killed at their 5m timeout → no usage
footer emitted). Their spend/tokens are unaccounted; true totals are marginally higher.

**Per-agent (whole run, main + gatekeeper):**

| Agent | Prompt tok | Output tok | Cache-read | Calls | ~Cost | Role |
|---|---:|---:|---:|---:|---:|---|
| k8s_leader | 9,224,936 | 77,281 | 0 | 549 | **~$6.10** | orchestrates; dominates cost (~97%) |
| k8s_investigator | 1,679,162 | 58,314 | 0 | 256 | ~$0.08 | read-only diagnosis (cheap tier) |
| k8s_auditor | 1,324,103 | 49,457 | 0 | 200 | ~$0.07 | gatekeeper policy audits (cheap tier) |
| k8s_editor | 547,570 | 12,042 | 0 | 80 | ~$0.03 | mutations (cheap tier; main-only) |
| **k8s_cleaner** *(new)* | 42,195 | 1,222 | 0 | 9 | ~$0.00 | teardown/cleanup helper — **not present in prior reports** |

- **Cost regime unchanged vs 07-06 run 1.** The leader still holds the premium tier and ~97% of
  spend (~$6.10 of $6.28); backing price out of a clean audit (e.g. `must-have-key`) still gives
  ~**$0.66/M input**. **Prompt caching is still off** (`cache_read_tok = 0` everywhere) — no
  change from run 1, still worth confirming intent on the omnis side.
- **A new `k8s_cleaner` agent** shows up in the per-agent tally (9 calls, negligible cost). It was
  absent from every prior report's fleet — a squad/fleet change that landed with the 13:07 rebuild.

## 7. Findings & recommendations

1. **Four regressions this run, and the failure *shape* changed.** `create-pod` (wrong image tag)
   and `create-network-policy` (egress spec shape) are new main losses; `allowed-reposv2`
   (5m timeout) and `unique-service-selector` (degenerate one-shot output) are new gatekeeper
   losses. All four coincide with the **13:07 `omnis-server` rebuild** — this run exercised a
   different omnis build than 07-06 run 1. Recommend diffing the squad/model changes in that build.
2. **`unique-service-selector` is the most concerning — it looks like a tool-call bug, not a skill
   gap.** The leader emitted the bare token `list_skills` as text and stopped after one call. If
   the new build intermittently serializes a tool call as prose, it will silently zero out any
   task. Worth reproducing in isolation (re-run just this task a few times) and checking the
   tool-call/shim path (`enableToolUseShim: false`).
3. **Two tasks blew their own 5-minute budget via a second audit pass.** `allowed-reposv2` and
   `pod-disruption-budget` both declare `timeout: 5m` in `task.yaml` (harness default is 10m). The
   audit playbook's "run an independent second pass with `k8s_auditor` to verify" is good for
   precision but too slow for these two. Either **tighten the two-pass audit** (only re-verify
   borderline resources, not a full re-enumeration) or accept that the strictest-timeout tasks
   need a faster single pass.
4. **`omnis-agent` leaks its spawned server when hard-killed on a task timeout (bug).** The
   harness SIGKILLs `omnis-agent` at the task's 5m timeout — **before** `omnis-agent`'s own 600s
   deadline and cleanup path — so the dedicated per-task server it spawned is **orphaned** (2 leaked
   this run: `allowed-reposv2`, `pod-disruption-budget`), along with its `/tmp/omnis-kab-*` home
   (§9). Fixes: (a) `omnis-agent` starts the child server in its **own process group** + installs a
   SIGTERM/SIGINT handler that kills it; and/or (b) `run.sh`'s `cleanup()` **sweeps leftover
   `omnis-kab-*` servers/dirs** at end-of-run as a backstop. This does **not** affect Pass@k (the
   harness scored stdout before the kill) but it accumulates zombie servers across runs.
5. **The recurring audit-precision losses are unchanged (4 of them).** Same guidance as prior runs:
   be **more conservative about compliant decoys** (over-reports on `container-limits-ignore-cpu`,
   `disallowed-tags`), and the two task-clarity cases (`disallow-anonymous`, `required-probes`)
   still penalize a defensible reading — worth filing upstream (strip proprietary detail first).
6. **`setup-dev-cluster` still fails on per-user RBAC** — the same `User`-subject Role/RoleBinding
   gap as 07-06 run 1. This is now a stable regression, not noise; targeted fix warranted.
7. **Cost/caching unchanged; new `k8s_cleaner` agent.** Spend flat at $6.28 (~97% leader),
   caching still off, ~$0.66/M leader. The new `k8s_cleaner` agent is cost-negligible but is a
   fleet change worth noting.

## 8. Comparison to prior runs

| | Run 1 (07-05) | Run 2 (07-05) | Run 1 (07-06) | **This run (07-06 r2)** | Δ vs 07-06 r1 |
|---|---:|---:|---:|---:|---:|
| Main | 24/24 (100%) | 24/24 (100%) | 23/24 (95.8%) | **21/24 (87.5%)** | **−2** |
| Gatekeeper | 24/31 (77.4%) | 26/31 (83.9%) | 25/31 (80.6%) | **24/31 (77.4%)** | **−1** |
| Total | 48/55 (87.3%) | 50/55 (90.9%) | 48/55 (87.3%) | **45/55 (81.8%)** | **−3** |
| Total cost | $21.41 | $29.29 | $6.05 | **$6.28** | +$0.23 |
| Cache-read tok | 0 | 6,640,926 | 0 | **0** | — |
| Wall | 1h39m | 2h02m | 2h21m | **2h43m** | +22m |

**Regressed to fail (vs 07-06 r1):** `create-pod` (wrong image), `create-network-policy` (egress
spec), `allowed-reposv2` (5m timeout), `unique-service-selector` (degenerate output).
**Recovered:** `block-endpoint-default-role`.
**Still failing (persistent core):** `setup-dev-cluster`, `container-limits-ignore-cpu`,
`disallow-anonymous`, `disallowed-tags`, `required-probes`; `pod-disruption-budget` also still
fails but this run via timeout rather than naming mismatch.

## 9. Teardown / server-leak note

Post-run state was clean **except** two orphaned per-task gatekeeper omnis-servers:

| PID | Task | Port | `OMNIS_HOME` | Cause |
|---|---|---|---|---|
| 2597988 | `allowed-reposv2` | :49171 | `/tmp/omnis-kab-ko4pryi6` | hard-killed at 5m timeout |
| 2709877 | `pod-disruption-budget` | :45663 | `/tmp/omnis-kab-12zt_ria` | hard-killed at 5m timeout |

Both were **reparented to systemd** (their `omnis-agent` parent died), bound to now-deleted task
kubeconfigs → harmless zombies. **Reaped by hand** (`kill` + `rm -rf` their temp homes); the dev
`:8080` instance was left untouched; no kind clusters remained. Root cause + fix in §7.4. **No
impact on Pass@k** — each task used its own cluster/server/port, so no cross-contamination, and the
harness scored each answer before the kill.

---

*Raw results (gitignored): `k8s-ai-bench/.build/full-main-run2/<task>/` and
`.build/full-gatekeeper-run2/<task>/` — each has `results.yaml`, `log.txt`, `trace.yaml`
(`log.txt` carries the per-agent `omnis-agent: usage …` footer, absent for the 2 timed-out tasks).
Run logs: `.build/logs-2026-07-06-run2/`.*
