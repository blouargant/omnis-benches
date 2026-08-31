# k8s-ai-bench — Full Run Report

**Date:** 2026-07-06 run 4 (run window 19:06:09Z → 20:49:55Z)
**Agent under test:** omnis (kubernetes squad, shipped unchanged, `bypassPermissions`)
**Scope:** Full suite — main (24 scored) + gatekeeper (31)
**Harness:** gke-labs/k8s-ai-bench @ `main` (`ac9ac9c`), `--concurrency 1` (sequential), kind ephemeral clusters

> Fourth full run on 2026-07-06, after the three earlier runs
> ([07-06 run 1](k8s-ai-bench-full-2026-07-06.md), [07-06 run 2](k8s-ai-bench-full-2026-07-06-run2.md),
> [07-06 run 3](k8s-ai-bench-full-2026-07-06-run3.md)) and the two 2026-07-05 runs
> ([run 1](k8s-ai-bench-full-2026-07-05.md), [run 2](k8s-ai-bench-full-2026-07-05-run2.md)).
> **The `omnis-server` binary was rebuilt at 21:03 local (19:03Z), 3 minutes before launch** — newer
> than the 07-06 run-3 build (15:28Z). So this run again exercises a **different omnis build**; treat
> as an omnis-side comparison, not a bench change.

## TL;DR

| Suite | Pass@1 | Rate | Cost | Wall |
|---|---|---:|---:|---:|
| **Main** | **23 / 24** | **95.8%** | $4.48 | 34m49s |
| **Gatekeeper** | **24 / 31** | **77.4%** | $3.65¹ | 1h08m57s |
| **Total** | **47 / 55** | **85.5%** | **$8.13¹** | **1h43m46s** |

¹ Gatekeeper/total cost **excludes 1 task** (`must-have-set-of-annotations`) that **hit its own
5-minute `task.yaml` timeout** and was hard-killed by the harness before `omnis-agent` could print its
usage footer — so its spend is unaccounted (true total is marginally higher). The same hard-kill
**orphaned its spawned omnis-server** (§9, reaped post-run).

omnis passed **23/24 main** and **24/31 gatekeeper**. **Total is flat vs 07-06 run 3 (47/55), but the
composition shifted:** main **+2** (two recoveries), gatekeeper **−2** (two new regressions).

- **Main recoveries:** `create-pod` (was wrong image tag `nginx:latest`) and `create-network-policy`
  (was unscoped DNS egress) **both pass** on this build. Only `setup-dev-cluster` still fails (same
  persistent per-user RBAC gap) — but it cost **$0.38** this run, down from $0.96 in run 3.
- **Gatekeeper regressions:** `must-have-set-of-annotations` (**new 5m timeout** → hard-kill → leaked
  server) and `block-wildcard-ingress` (**new non-convergence** — looped on exploratory `jq`/`kubectl`
  and never emitted a clean `VIOLATING:` verdict). Both passed in run 3.
- `pod-disruption-budget` still fails but the **mode changed**: run 3 was a 5m timeout; this run it
  **finished** (footer present) and gave a wrong answer (named the PDB, not the target workload
  `resource-007`).

**Cost jumped +28% ($6.37 → $8.13).** The leader tier is unchanged (~$0.66/M effective, still ~$6.77),
but **every sub-agent tier is materially pricier on this build** — the registry now maps
`k8s_investigator → high` and `k8s_auditor`/`k8s_editor`/`k8s_cleaner → balanced`, so the sub-agent
spend rose ~10× in aggregate ($0.14 → $1.35). Caching still off (`cache_read_tok = 0` everywhere).

---

## 1. Environment

| Component | Version / value |
|---|---|
| k8s-ai-bench | gke-labs/k8s-ai-bench @ `main` (`ac9ac9c`) — same commit as all prior 07-06 runs |
| omnis-server | **rebuilt 21:03 local / 19:03Z (`/usr/bin/omnis-server`, 41 MB)** — newer than 07-06 run 3 |
| kind | shared cluster `k8s-ai-bench-eval` (main); per-task throwaway clusters (gatekeeper) |
| tooling | docker · kubectl · helm · go (all on PATH) |
| squad | `kubernetes` (shipped), `bench-permissions.json` = `bypassPermissions` |
| model fleet | tiered — leader `premium`, investigator `high`, auditor/editor/cleaner `balanced`; **caching off** |
| concurrency | **1 (sequential)** via the `CONCURRENCY` knob in `run.sh` |

**Fleet tier map (from `/etc/omnis` + `$HOME/.omnis` registry & `models.json`):**

| Agent | `model_ref` | input $/M | output $/M | cache-in $/M |
|---|---|---:|---:|---:|
| k8s_leader | `premium` | 3.15 | 15.75 | 0.30 |
| k8s_investigator | `high` | 0.63 | 3.78 | — |
| k8s_auditor / k8s_editor / k8s_cleaner | `balanced` | 0.26 | 1.58 | — |

## 2. Methodology

Two phases, back-to-back, **sequential**, into **separate, fresh output dirs**
(`full-main-run4` / `full-gatekeeper-run4`) so prior raw data was preserved and
`horizontal-pod-autoscaler` — which exists in *both* suites — could not clobber itself:

- **Phase 1 — main / shared-cluster path** (`TASK_PATTERN='^[^g]'`, `.build/full-main-run4`).
  One kind cluster (`k8s-ai-bench-eval`) + **one** multiplexed omnis-server on a random port
  (`:41833`); every task opens a session on it. 19:06:09Z → 19:40:58Z (34m49s).
- **Phase 2 — gatekeeper / `isolation: cluster` path** (`TASKS_DIR=…/tasks/gatekeeper`,
  `.build/full-gatekeeper-run4`). The harness creates a **dedicated throwaway cluster per task**;
  `omnis-agent` spawns a dedicated omnis-server for each (random port, own `OMNIS_HOME`), installs
  Gatekeeper/OPA, runs, tears down. 19:40:58Z → 20:49:55Z (1h08m57s).

`fix-oomkilled` is disabled upstream (skipped), so **55 tasks were scored**, not 56.

> **Why sequential.** The upstream harness treats `--concurrency 0` (its default) as
> *"auto = number of tasks"* — it runs **every task at once**, which on the shared
> single-cluster/single-server kind path causes contention + model-endpoint flooding → noisy
> pass/fail. `run.sh` defaults to `CONCURRENCY=1`.

**Teardown.** After the run: **no kind clusters remained** (`run.sh` deleted the shared cluster; the
harness + `omnis-agent` deleted each per-task gatekeeper cluster). **One per-task gatekeeper server
leaked** (`must-have-set-of-annotations`, hard-killed at its 5m timeout) — see §9; reaped by hand
post-run. (The unrelated omnis-server on default port `:8080` is the interactive dev instance; not a
bench process, left untouched.)

## 3. Results — Main suite (23 / 24 = 95.8%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| create-canary-deployment | ✅ | 1m21s | $0.31 |
| create-network-policy *(recovered)* | ✅ | 0m37s | $0.09 |
| create-pod *(recovered)* | ✅ | 0m28s | $0.06 |
| create-pod-mount-configmaps | ✅ | 0m47s | $0.15 |
| create-pod-resources-limits | ✅ | 0m35s | $0.10 |
| create-simple-rbac | ✅ | 0m26s | $0.09 |
| debug-app-logs | ✅ | 1m20s | $0.09 |
| deployment-traffic-switch | ✅ | 0m59s | $0.16 |
| fix-crashloop | ✅ | 3m05s | $0.27 |
| fix-image-pull | ✅ | — | $0.12 |
| fix-pending-pod | ✅ | 1m04s | $0.16 |
| fix-probes | ✅ | 1m45s | $0.16 |
| fix-rbac-wrong-resource | ✅ | 0m39s | $0.14 |
| fix-service-routing | ✅ | 0m57s | $0.19 |
| fix-service-with-no-endpoints | ✅ | 1m56s | $0.23 |
| horizontal-pod-autoscaler | ✅ | 1m25s | $0.15 |
| list-images-for-pods | ✅ | 1m39s | $0.09 |
| multi-container-pod-communication | ✅ | 1m23s | $0.18 |
| resize-pvc | ✅ | 4m21s | $0.87 |
| rolling-update-deployment | ✅ | 1m07s | $0.16 |
| scale-deployment | ✅ | 0m35s | $0.09 |
| scale-down-deployment | ✅ | 0m35s | $0.09 |
| **setup-dev-cluster** | ❌ | 2m07s | $0.38 |
| statefulset-lifecycle | ✅ | 3m27s | $0.15 |

*\*Times are approximate — derived from consecutive `results.yaml` write times (includes each
task's setup + verify). The first-completing task's delta is omitted (folds in cluster warm-up).
Costs are exact from `omnis-agent`'s per-task `est_cost_usd`.*

## 4. Results — Gatekeeper suite (24 / 31 = 77.4%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| allowed-ip | ✅ | 1m59s | $0.10 |
| allowed-repos | ✅ | 5m05s | $0.11 |
| allowed-reposv2 | ✅ | 4m12s | $0.20 |
| automount-serviceaccount-token | ✅ | 1m09s | $0.09 |
| block-endpoint-default-role | ✅ | 2m02s | $0.15 |
| **block-wildcard-ingress** *(new regression)* | ❌ | 3m11s | $0.14 |
| block-loadbalancer-services | ✅ | 1m30s | $0.09 |
| container-cpu-requests-memory-limits-and-requests | ✅ | 1m54s | $0.10 |
| container-image-must-have-digest | ✅ | 2m01s | $0.11 |
| container-limits | ✅ | 1m55s | $0.11 |
| container-limits-and-requests | ✅ | 1m22s | $0.11 |
| **container-limits-ignore-cpu** | ❌ | 1m51s | $0.11 |
| container-requests | ✅ | 1m53s | $0.10 |
| **disallow-anonymous** | ❌ | 2m00s | $0.12 |
| disallow-interactive | ✅ | 1m43s | $0.16 |
| **disallowed-tags** | ❌ | 2m58s | $0.12 |
| ephemeral-storage-limit | ✅ | 2m21s | $0.16 |
| horizontal-pod-autoscaler | ✅ | 2m05s | $0.10 |
| memory-and-cpu-ratios | ✅ | 2m13s | $0.12 |
| memory-ratio-only | ✅ | 2m24s | $0.15 |
| must-have-key | ✅ | — | $0.10 |
| must-have-owner | ✅ | 2m34s | $0.14 |
| **must-have-set-of-annotations** *(new regression — timeout)* | ❌ timeout | 5m06s | — (no footer) |
| **pod-disruption-budget** | ❌ | 2m12s | $0.29 |
| replica-limit | ✅ | 2m09s | $0.12 |
| repo-must-not-be-k8s-gcr-io | ✅ | 1m57s | $0.10 |
| **required-probes** | ❌ | 2m42s | $0.15 |
| tls-optional | ✅ | 1m19s | $0.10 |
| tls-required | ✅ | 1m03s | $0.07 |
| unique-ingress-host | ✅ | 1m03s | $0.06 |
| unique-service-selector | ✅ | 0m55s | $0.05 |

*\*Same caveat as §3; gatekeeper deltas also fold in the **next** task's cluster creation + OPA
install (so they're inflated). `must-have-set-of-annotations`'s delta reflects the harness's hard
5m00s cutoff.*

## 5. Failure analysis (8 losses)

### 5.1 Main (1 loss — persistent)

| Task | Type | What happened |
|---|---|---|
| **setup-dev-cluster** *(persistent)* | partial RBAC | `FAIL: alice (User) cannot create pods in their own namespace 'dev-alice'`. Namespaces + developer ServiceAccounts created, but the per-**user** pod-create RBAC (Role/RoleBinding for the `User` subject) is still missing/wrong. **Same multi-step RBAC gap as runs 1–3.** This run it was cheaper/faster ($0.38 / 2m07s vs $0.96 / 7m55s in run 3) but still failed. |

### 5.2 Gatekeeper (7 losses)

Read-only audit tasks: the agent lists policy-violating resources, one `VIOLATING: <name>` line each,
scored by `expect` substrings (`contains`/`notContains`). Tasks seed **compliant decoys** (catch
over-reporting) and **subtle violations** (catch under-reporting).

**Persistent (5 — same tasks/causes as prior runs):**

| Task | Type | What happened |
|---|---|---|
| **container-limits-ignore-cpu** | over-report | Flagged the compliant boundary decoy `resource-001` (`notContains` tripped). **Same `≤` vs `<` misread as prior runs.** |
| **disallowed-tags** | over-report | Flagged a compliant decoy the grader's `notContains` rejects (`resource-002`). **Same registry-port/decoy over-report pattern.** |
| **disallow-anonymous** *(task-ambiguous)* | over-report | Flagged the compliant decoy `resource-001`; prompt wording (`anonymous` **or** `unauthenticated`) makes this defensible. **Same as prior runs.** |
| **required-probes** *(task-ambiguous)* | under-report | Read the rule too loosely and missed a `contains` target (`VIOLATING: resource-002`). **Same under-report as prior runs.** |
| **pod-disruption-budget** *(mode changed)* | wrong name | **This run it finished** (footer $0.29, no timeout — unlike run 3's hard-kill). It correctly identified the offending PDB (`inventory-nginx-pdb-disallowed`, `minAvailable=3` = replica count) but reported the **PDB's own name instead of the target workload** `resource-007` the grader expects (`contains "VIOLATING: resource-007"` missed). |

**New regressions (2 — passed in run 3):**

| Task | Type | What happened |
|---|---|---|
| **must-have-set-of-annotations** *(new — timeout)* | **timeout** | `task timed out after 5m0s` (task's own `timeout: 5m`; `isolation: cluster`). The agent was still mid-investigation (delegating a Services-annotation audit to `k8s_investigator`, retrying a "fix the call format" step) when the harness SIGKILLed `omnis-agent` at the 5m boundary → **no usage footer, leaked server (§9)**. Passed in run 3. |
| **block-wildcard-ingress** *(new — non-convergence)* | non-convergence | The agent **looped on exploratory `jq`/`kubectl get ingress -o json` calls** (repeatedly reshaping the same query) and never emitted a clean final `VIOLATING: resource-004` verdict; the grader's `contains` regex found only the transcript of tool calls. Finished (footer $0.14), so not a timeout — a **behaviour failure** where it over-explored and didn't converge to the required output format. Passed in run 3. |

**Breakdown:** 4 over/under-report (persistent audit precision) · 1 wrong-name (`pod-disruption-budget`)
· 1 timeout (`must-have-set-of-annotations`) · 1 non-convergence (`block-wildcard-ingress`).

## 6. Cost & token economics

| Metric | This run (07-06 run 4) | 07-06 run 3 |
|---|---:|---:|
| Total cost | **$8.13**¹ | $6.37¹ |
| — Main | $4.48 | $4.24 |
| — Gatekeeper | $3.65¹ | $2.13¹ |
| Prompt tokens | 14,314,383¹ | 12,077,372¹ |
| Output tokens | 270,442¹ | 177,206¹ |
| **Cache-read tokens** | **0** | 0 |

¹ Excludes `must-have-set-of-annotations` (killed at its 5m timeout → no usage footer). Its
spend/tokens are unaccounted; true totals are marginally higher.

**Per-agent (whole run, main + gatekeeper):**

| Agent | Prompt tok | Output tok | Cache-read | Calls | ~Cost | Role |
|---|---:|---:|---:|---:|---:|---|
| k8s_leader | 10,242,850 | 84,740 | 0 | 611 | **~$6.77** | orchestrates; dominates cost (~83%) |
| k8s_investigator | 2,150,522 | 97,387 | 0 | 241 | ~$0.71 | read-only diagnosis (now `high` tier) |
| k8s_auditor | 1,710,920 | 82,583 | 0 | 218 | ~$0.58 | gatekeeper policy audits (`balanced`) |
| k8s_editor | 156,983 | 3,492 | 0 | 19 | ~$0.05 | mutations (`balanced`; main-only) |
| k8s_cleaner | 53,108 | 2,240 | 0 | 8 | ~$0.02 | teardown/cleanup helper (`balanced`) |

- **Cost jumped +28% (+$1.76) — driven by the sub-agent tiers, not the leader.** The leader's
  effective input rate backs out to **$0.661/M** — unchanged from every prior run — and its ~$6.77
  tracks its token volume. What changed is the **non-leader spend, up ~10× in aggregate ($0.14 →
  $1.35)**: `k8s_investigator` $0.07 → **$0.71**, `k8s_auditor` $0.06 → **$0.58**. Two compounding
  causes: (a) the registry now puts investigator on `high` (0.63/M) and auditor/editor/cleaner on
  `balanced` (0.26/M) — materially pricier than run 3's effective ~$0.05/M sub-agent rate; and (b)
  higher sub-agent token volume this run (investigator prompt 1.31M → 2.15M; auditor gatekeeper-heavy).
- **`pod-disruption-budget` did the whole audit on the leader** (all 611… of its footer was
  `k8s_leader`, prompt 438k, $0.29) instead of delegating to the cheap auditor — a pattern worth
  watching, since leader-only audits are ~5× the per-token cost of the `balanced` auditor.
- **`resize-pvc` remains the single-task cost outlier** ($0.87, 4m21s) — still passes.
- **Prompt caching is still off** (`cache_read_tok = 0` everywhere) — no change, still worth
  confirming intent on the omnis side; a working cache would meaningfully cut the leader's ~$6.77.

## 7. Findings & recommendations

1. **Total flat (47/55) but the failure surface moved.** Main **recovered** `create-pod` and
   `create-network-policy` (both persistent fails in run 3), leaving `setup-dev-cluster` as the lone
   main loss. Gatekeeper **regressed** on `must-have-set-of-annotations` (new 5m timeout) and
   `block-wildcard-ingress` (new non-convergence). Net-zero on score, but the two gatekeeper
   regressions are new and worth watching on the next build.
2. **`block-wildcard-ingress` non-convergence is the most concerning new failure.** The agent looped
   reshaping the same `kubectl get ingress -o json | jq …` query and never produced the required
   `VIOLATING:` line. This is an *output-discipline* failure, not a reasoning one — the audit skill
   should cap exploratory re-queries and force a single structured verdict. Tighten the k8s-audit
   playbook's stop condition (numbered procedure + "emit exactly one VIOLATING block, then stop").
3. **`must-have-set-of-annotations` is a fresh timeout — and the recurring leak source.** It tipped
   over its own 5m `task.yaml` budget (harness default is 10m) and was hard-killed → no footer +
   **leaked per-task server** (§9). Same class as run 3's `pod-disruption-budget`. The two fixes are
   unchanged: (a) `omnis-agent` should start the child server in its **own process group** + install a
   SIGTERM/SIGINT handler that kills it; and/or (b) `run.sh`'s `cleanup()` should **sweep leftover
   `omnis-kab-*` servers/dirs** at end-of-run. **No Pass@k impact**, but zombies accumulate.
4. **`pod-disruption-budget` is one rename away from passing.** It finished under budget this run and
   found the right violation, but reported the PDB's name (`inventory-nginx-pdb-disallowed`) rather
   than the target workload (`resource-007`). The audit skill should normalise "report the offending
   *workload*, by the resource name the task seeds" for PDB-style rules.
5. **Cost regressed +28% via the sub-agent tiers.** Leader economics are unchanged (~$0.66/M, ~$6.77),
   but investigator (`high`) + auditor (`balanced`) now cost ~10× their run-3 total. If the intent was
   to upgrade sub-agent quality, the +$1.76 bought two *regressions* this run — worth re-checking
   whether `high`/`balanced` sub-agents actually improve Pass@k vs the cheaper prior tiers, or whether
   this is spend without benefit. **Verify the tier map is deliberate**, not an accidental registry
   drift (`$HOME/.omnis` overrides `/etc/omnis` for investigator + leader).
6. **`setup-dev-cluster` still fails but is no longer a cost sink** ($0.38 vs $0.96). Same
   `User`-subject Role/RoleBinding gap as runs 1–3 — a targeted squad/prompt fix would recover the
   pass.
7. **Recurring audit-precision losses unchanged (4).** Be **more conservative about compliant decoys**
   (`container-limits-ignore-cpu` `≤`-boundary, `disallowed-tags`), and the two task-clarity cases
   (`disallow-anonymous`, `required-probes`) still penalize a defensible reading — worth filing
   upstream (strip proprietary detail first).
8. **Caching still off.** `cache_read_tok = 0` everywhere; a working prompt cache would cut the
   dominant leader cost — still worth confirming intent on the omnis side.

## 8. Comparison to prior runs

| | Run 1 (07-05) | Run 2 (07-05) | Run 1 (07-06) | Run 2 (07-06) | Run 3 (07-06) | **This run (07-06 r4)** | Δ vs 07-06 r3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Main | 24/24 (100%) | 24/24 (100%) | 23/24 (95.8%) | 21/24 (87.5%) | 21/24 (87.5%) | **23/24 (95.8%)** | **+2** |
| Gatekeeper | 24/31 (77.4%) | 26/31 (83.9%) | 25/31 (80.6%) | 24/31 (77.4%) | 26/31 (83.9%) | **24/31 (77.4%)** | **−2** |
| Total | 48/55 (87.3%) | 50/55 (90.9%) | 48/55 (87.3%) | 45/55 (81.8%) | 47/55 (85.5%) | **47/55 (85.5%)** | **0** |
| Total cost | $21.41 | $29.29 | $6.05 | $6.28 | $6.37 | **$8.13** | +$1.76 |
| Cache-read tok | 0 | 6,640,926 | 0 | 0 | 0 | **0** | — |
| Wall | 1h39m | 2h02m | 2h21m | 2h43m | 2h21m | **1h44m** | −37m |

**Recovered (vs 07-06 r3):** `create-pod` (wrong image → pass), `create-network-policy` (unscoped DNS
egress → pass).
**Regressed to fail:** `must-have-set-of-annotations` (pass → 5m timeout), `block-wildcard-ingress`
(pass → non-convergence).
**Still failing (persistent core):** `setup-dev-cluster` (main); `container-limits-ignore-cpu`,
`disallow-anonymous`, `disallowed-tags`, `required-probes`, `pod-disruption-budget` (gatekeeper).

## 9. Teardown / server-leak note

Post-run state was clean **except** one orphaned per-task gatekeeper omnis-server:

| PID | Task | Port | `OMNIS_HOME` | Cause |
|---|---|---|---|---|
| 3964638 | `must-have-set-of-annotations` | :56459 | `/tmp/omnis-kab-vz5_o5gp` | hard-killed at 5m timeout |

**Reparented to systemd** (its `omnis-agent` parent died), bound to the now-deleted task kubeconfig →
harmless zombie. **Reaped by hand** (`kill` + `rm -rf` its temp home); the dev `:8080` instance was
left untouched; no kind clusters remained; no other `/tmp/omnis-kab-*` homes survived. Root cause +
fix in §7.3. **No impact on Pass@k** — the task used its own cluster/server/port, so no
cross-contamination, and the harness scored (an empty) stdout before the kill.

---

*Raw results (gitignored): `k8s-ai-bench/.build/full-main-run4/<task>/` and
`.build/full-gatekeeper-run4/<task>/` — each has `results.yaml`, `log.txt`, `trace.yaml`
(`log.txt` carries the per-agent `omnis-agent: usage …` footer, absent for the 1 timed-out task).
Run logs: `.build/logs-2026-07-06-run4/`.*
