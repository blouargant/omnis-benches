# k8s-ai-bench — Full Run Report (run 2)

**Date:** 2026-07-05 (run window 16:22:36Z → 18:24:54Z)
**Agent under test:** omnis (kubernetes squad, shipped unchanged, `bypassPermissions`)
**Scope:** Full suite — main (24 scored) + gatekeeper (31)
**Harness:** gke-labs/k8s-ai-bench @ `main`, `--concurrency 1` (sequential), kind ephemeral clusters

> Second full run of the day. The earlier report
> ([k8s-ai-bench-full-2026-07-05.md](k8s-ai-bench-full-2026-07-05.md)) is preserved for
> comparison — see §8. Two gatekeeper tasks that failed there now pass.

## TL;DR

| Suite | Pass@1 | Rate | Cost | Wall |
|---|---|---:|---:|---:|
| **Main** | **24 / 24** | **100%** | $16.42 | 54m04s |
| **Gatekeeper** | **26 / 31** | **83.9%** | $12.87 | 68m14s |
| **Total** | **50 / 55** | **90.9%** | **$29.29** | **2h02m18s** |

omnis **swept the entire main suite (24/24)** again. Gatekeeper rose to **26/31 (from 24/31)**:
`allowed-repos` and `automount-serviceaccount-token` — both failures last run — now pass. All 5
remaining losses are gatekeeper **audit-precision** errors (over/under-reporting policy
violations), not execution or infra failures. 0 errors, 0 setup aborts. `fix-oomkilled` is
disabled upstream, so 55 tasks were scored, not 56.

Two squad-side changes vs the earlier run are visible in the traces: a **dedicated
`k8s_auditor` agent** now drives gatekeeper audits (dual-pass investigator/auditor
reconciliation), and **prompt caching is now active** (`cache_read_tok` non-zero everywhere;
it was 0 last run).

---

## 1. Environment

| Component | Version / value |
|---|---|
| k8s-ai-bench | gke-labs/k8s-ai-bench @ `main` |
| kind | shared cluster `k8s-ai-bench-eval` (main); per-task throwaway clusters (gatekeeper) |
| tooling | kubectl · helm · go (all on PATH) |
| squad | `kubernetes` (shipped), `bench-permissions.json` = `bypassPermissions` |
| model fleet | omnis's tiered fleet (premium leader + cheap sub-agents — see §6) |
| concurrency | **1 (sequential)** via the `CONCURRENCY` knob in `run.sh` |

## 2. Methodology

Two phases, back-to-back, **sequential**, into **separate output dirs** (`horizontal-pod-autoscaler`
exists in *both* suites, so a shared dir would clobber one):

- **Phase 1 — main / shared-cluster path** (`TASK_PATTERN='^[^g]'`, `.build/full-main`).
  One kind cluster (`k8s-ai-bench-eval`) + **one** multiplexed omnis-server; every task opens a
  session on it.
- **Phase 2 — gatekeeper / `isolation: cluster` path** (`TASKS_DIR=…/tasks/gatekeeper`,
  `.build/full-gatekeeper`). The harness creates a **dedicated throwaway cluster per task**;
  `omnis-agent` spawns a dedicated omnis-server for each (random port, own `OMNIS_HOME`),
  installs Gatekeeper/OPA, runs, tears down.

> **Why sequential.** The upstream harness treats `--concurrency 0` (its default) as
> *"auto = number of tasks"* — it runs **every task at once**, which on the shared
> single-cluster/single-server kind path causes contention + model-endpoint flooding → noisy
> pass/fail. `run.sh` defaults to `CONCURRENCY=1`.

**Clean teardown verified.** No leftover bench clusters; run.sh stopped both shared servers.
(One unrelated omnis-server remains on the default port `:8080` — your interactive dev instance
running from `~/Documents/Dev/omnis`; it is not a bench process and was left untouched.)

## 3. Results — Main suite (24 / 24 = 100%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| create-canary-deployment | ✅ | — | $0.92 |
| create-network-policy | ✅ | 0m33s | $0.26 |
| create-pod | ✅ | 1m11s | $0.16 |
| create-pod-mount-configmaps | ✅ | 1m23s | $0.55 |
| create-pod-resources-limits | ✅ | 0m34s | $0.26 |
| create-simple-rbac | ✅ | 1m16s | $0.65 |
| debug-app-logs | ✅ | 1m19s | $0.24 |
| deployment-traffic-switch | ✅ | 2m09s | $0.78 |
| fix-crashloop | ✅ | 2m15s | $0.66 |
| fix-image-pull | ✅ | 2m41s | $0.71 |
| fix-pending-pod | ✅ | 1m54s | $0.34 |
| fix-probes | ✅ | 1m41s | $0.35 |
| fix-rbac-wrong-resource | ✅ | 1m51s | $0.35 |
| fix-service-routing | ✅ | 3m14s | $0.81 |
| fix-service-with-no-endpoints | ✅ | 2m56s | $0.92 |
| horizontal-pod-autoscaler | ✅ | 1m43s | $0.23 |
| list-images-for-pods | ✅ | 1m07s | $0.52 |
| multi-container-pod-communication | ✅ | 4m01s | $1.12 |
| resize-pvc | ✅ | 2m10s | $0.36 |
| rolling-update-deployment | ✅ | 5m21s | $1.36 |
| scale-deployment | ✅ | 1m21s | $0.30 |
| scale-down-deployment | ✅ | 1m08s | $0.22 |
| setup-dev-cluster | ✅ | 5m12s | $2.90 |
| statefulset-lifecycle | ✅ | 3m10s | $1.47 |

*\*Times are approximate — derived from consecutive `results.yaml` write times (includes each
task's setup + verify). The first task's delta is omitted (folds in cluster warm-up). Costs are
exact from `omnis-agent`'s per-task `est_cost_usd`.*

`debug-app-logs` passed cleanly (1m19s) — no fresh-cluster `default`-ServiceAccount race this run.

## 4. Results — Gatekeeper suite (26 / 31 = 83.9%)

| Task | Result | Time* | Cost |
|---|---|---:|---:|
| allowed-ip | ✅ | 1m39s | $0.37 |
| allowed-repos | ✅ | 4m42s | $0.35 |
| allowed-reposv2 | ✅ | 5m26s | $0.43 |
| automount-serviceaccount-token | ✅ | 1m42s | $0.38 |
| block-endpoint-default-role | ✅ | 2m06s | $0.40 |
| block-loadbalancer-services | ✅ | 1m24s | $0.34 |
| block-wildcard-ingress | ✅ | 2m11s | $0.46 |
| container-cpu-requests-memory-limits-and-requests | ✅ | 1m53s | $0.37 |
| container-image-must-have-digest | ✅ | 2m08s | $0.41 |
| container-limits | ✅ | 2m16s | $0.71 |
| container-limits-and-requests | ✅ | 2m27s | $0.40 |
| container-limits-ignore-cpu | ❌ | 2m29s | $0.42 |
| container-requests | ✅ | 2m27s | $0.71 |
| disallow-anonymous | ❌ | 1m35s | $0.37 |
| disallow-interactive | ✅ | 1m49s | $0.37 |
| disallowed-tags | ❌ | 1m59s | $0.36 |
| ephemeral-storage-limit | ✅ | 1m58s | $0.38 |
| horizontal-pod-autoscaler | ✅ | 2m11s | $0.40 |
| memory-and-cpu-ratios | ✅ | 2m40s | $0.45 |
| memory-ratio-only | ✅ | 2m00s | $0.39 |
| must-have-key | ✅ | 1m31s | $0.35 |
| must-have-owner | ✅ | 1m51s | $0.68 |
| must-have-set-of-annotations | ✅ | 1m52s | $0.40 |
| pod-disruption-budget | ❌ | 3m09s | $0.56 |
| replica-limit | ✅ | — | $0.35 |
| repo-must-not-be-k8s-gcr-io | ✅ | 1m50s | $0.28 |
| required-probes | ❌ | 1m57s | $0.38 |
| tls-optional | ✅ | 1m53s | $0.36 |
| tls-required | ✅ | 1m46s | $0.35 |
| unique-ingress-host | ✅ | 1m38s | $0.36 |
| unique-service-selector | ✅ | 1m29s | $0.34 |

## 5. Gatekeeper failure analysis (5 losses)

These are **read-only audit tasks**: the agent lists resources that *violate* a policy, one
`VIOLATING: <name>` line each, scored by `expect` substrings (`contains`/`notContains`). Tasks
are seeded with **compliant decoys** (to catch over-reporting) and **subtle violations** (to
catch under-reporting). This run's 5 losses:

| Task | Type | What happened |
|---|---|---|
| **container-limits-ignore-cpu** | over-report | Correctly flagged `resource-002` but **also** flagged the compliant `resource-001` — read a `1Gi` memory limit as violating a `< 1Gi` rule (boundary `≤` vs `<` misread). |
| **disallowed-tags** | over-report | Correctly found `resource-003…006` (incl. the subtle `openpolicyagent:443/opa` "colon is a registry port, not a tag" case) but flagged the compliant decoy `resource-002`. |
| **disallow-anonymous** | over-report / task-ambiguous | Flagged `resource-001` and `system:public-info-viewer` in addition to `resource-002`. All bind `system:unauthenticated`; only `resource-002` also binds `system:anonymous`. The prompt says flag `anonymous` **or** `unauthenticated`, so the extra flags are *defensible per the wording* — a task-clarity issue as much as an agent error. |
| **pod-disruption-budget** | naming mismatch | **Found the right violating PDB** (`minAvailable=3 == replicas=3`) but reported it by its real name `inventory-nginx-pdb-disallowed` instead of the grader's alias `resource-007`, so the `contains: VIOLATING: resource-007` check missed. Detection correct; identifier convention wrong. |
| **required-probes** | under-report / task-ambiguous | Concluded **all 3 pods compliant**, missing `resource-002` and `resource-003`. It read the policy as "≥1 probe anywhere in the pod"; the grader wants stricter per-container readiness+liveness coverage. Scope ambiguity in the task ("missing both a readiness and liveness probe"). |

**Breakdown:** 3 over-reports · 1 naming-convention mismatch · 1 under-report. Two of the five
(`disallow-anonymous`, `required-probes`) hinge on **under-specified task wording** and penalize
a defensible reading. None are execution/permission/infra failures.

**What improved since last run.** The earlier report's #1 root cause was *fields off the happy
path get skipped* — the clearest case being `allowed-repos`, where the agent audited only
`spec.containers` and missed an `initContainer`. That is now **fixed**: the new `k8s_auditor`
explicitly enumerates `initContainers`/`ephemeralContainers` (visible in the
`container-limits-ignore-cpu` trace, which runs `jq` for `hasInit`/`hasEphemeral`), and
`allowed-repos` now passes. `automount-serviceaccount-token` also flipped to pass.

## 6. Cost & token economics

| Metric | Value |
|---|---|
| Total cost | **$29.29** ($16.42 main + $12.87 gatekeeper) |
| Avg cost / task | $0.68 main · $0.42 gatekeeper |
| Prompt tokens | 13,437,563 |
| Output tokens | 232,979 |
| **Cache-read tokens** | **6,640,926** (was 0 last run) |

**Per-agent (whole run, main + gatekeeper):**

| Agent | Prompt tok | Output tok | Cache-read | Calls | ~Cost | Role |
|---|---:|---:|---:|---:|---:|---|
| k8s_leader | 6,997,263 | 86,826 | 6,640,926 | 405 | **~$25.40** | orchestrates; **premium tier → dominates cost** |
| k8s_investigator | 3,230,879 | 66,803 | 0 | 409 | ~$2.29 | read-only diagnosis (cheap tier) |
| k8s_auditor | 2,134,332 | 54,578 | 0 | 270 | ~$1.55 | **new** — gatekeeper policy audits (cheap tier) |
| k8s_editor | 1,075,089 | 24,772 | 0 | 173 | ~$0.05 | mutations (cheap tier) |

- **The leader still dominates spend (~87%).** It holds the premium tier and the bulk of prompt
  tokens; the worker agents doing the actual kubectl/audit work are 10–500× cheaper.
- **Prompt caching is now on** — all 6.64M cache-read tokens are the leader's, exactly the
  agent the earlier report flagged as re-sending large static context uncached. Caching is
  landing where it matters most.
- **Total cost rose vs last run ($21 → $29)** despite caching, driven by the gatekeeper suite
  ($5.79 → $12.87): the new dual-pass investigator/auditor reconciliation does substantially
  more work per audit. That extra spend bought +2 passing tasks and a fixed `initContainer`
  blind spot — a reasonable accuracy/cost trade, but worth watching if gatekeeper cost keeps
  climbing.

## 7. Findings & recommendations

1. **Main-suite competence is rock-solid: 24/24, twice.** Create, fix, scale, debug,
   traffic-switch, PVC resize, statefulset and dev-cluster setup all pass with the shipped
   squad — no narration-instead-of-acting failures; `bypassPermissions` does its job.
2. **Gatekeeper improved (24→26) on exactly the recommended axis.** The `initContainer` blind
   spot is closed via the new `k8s_auditor`. Remaining gains are precision on decoys: the audit
   playbook should be **more conservative about flagging borderline/compliant resources**
   (3 of 5 losses are over-reports) and **exact about grader identifiers** (report the
   `resource-NNN` alias, not the resource's own `metadata.name` — cost `pod-disruption-budget`).
3. **File upstream task-clarity issues** for `disallow-anonymous` (prompt says
   `anonymous` OR `unauthenticated`, grader wants only the `anonymous` binding) and
   `required-probes` ("missing both" per-pod vs per-container scope) — both penalize a
   defensible reading. *(Strip any proprietary detail before filing.)*
4. **Watch gatekeeper cost.** The dual-pass audit more than doubled gatekeeper spend. If the
   accuracy plateaus, consider gating the second pass on low-confidence audits only.
5. **Infra & harness healthy.** Sequential execution, shared-server multiplexing (main),
   per-task dedicated servers + OPA installs + cluster teardowns (gatekeeper) all worked; no
   leftover clusters/processes; 0 setup aborts this run.

## 8. Comparison to the earlier run (same day)

| | Earlier run | This run (run 2) | Δ |
|---|---:|---:|---:|
| Main | 24/24 (100%) | 24/24 (100%) | = |
| Gatekeeper | 24/31 (77.4%) | **26/31 (83.9%)** | **+2** |
| Total | 48/55 (87.3%) | **50/55 (90.9%)** | **+2** |
| Total cost | $21.41 | $29.29 | +$7.88 |
| Cache-read tok | 0 | 6,640,926 | caching on |
| Gatekeeper agent model | leader-mostly | **+ dedicated `k8s_auditor`** | new |

**Flipped to pass:** `allowed-repos` (initContainer blind spot fixed), `automount-serviceaccount-token`.
**Still failing (both runs):** `container-limits-ignore-cpu`, `disallow-anonymous`,
`disallowed-tags`, `pod-disruption-budget`, `required-probes` — the audit-precision / task-clarity core.

---

*Raw results (gitignored): `k8s-ai-bench/.build/full-main/<task>/` and
`.build/full-gatekeeper/<task>/` — each has `results.yaml`, `log.txt`, `trace.yaml` (trace
carries the per-agent usage footer).*
