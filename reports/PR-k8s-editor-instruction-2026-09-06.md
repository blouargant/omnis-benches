## Summary

`k8s_editor`'s instruction predates the change-validation layer and now contradicts it in three places. The agent pays for that in turns: it discovers the attestation workflow by being refused, and it is explicitly told to do the opposite of what the guard's diagnostics are designed for.

Two commits, separable — the first is a factual correction, the second is a behavioural proposal.

| commit | what | confidence |
|---|---|---|
| `78cd667` | fixes three statements that are **false** since the guard shipped | verified against a live cluster |
| `2cb223c` | teaches the attestation workflow and the terminal-capability case | **A/B measured — its stated mechanism is falsified, see below** |

## What is factually wrong today

**Step 4 promised a dry-run preview.** The guard admits a command only when it is provably read-only, and no spelling of `apply` is. Probed against a live kind cluster:

| command | verdict |
|---|---|
| `kubectl diff -f x.yaml` | allow |
| `kubectl apply --dry-run=server -f x.yaml` | **deny** |
| `kubectl apply --server-side --dry-run=server -f x.yaml` | **deny** |
| `helm upgrade … --dry-run` | **deny** (attestation required) |

A model hit this mid-task and narrated it: *"The hook is flagging `kubectl apply` even for dry-run."* Step 5's Helm bullet carried the same promise and is corrected too.

**Step 6 told the agent to stop on a refusal** — *"If a call is denied, report it and stop — do not retry with a different flag or identity."* That is the opposite of the guard's design. `refuse()` returns a diagnostic precisely so the agent can correct and retry, and only escalates after `MAX_ATTEMPTS`. And under `bypassPermissions` there is no confirmation prompt at all, so the premise of the sentence is gone as well.

## The measured cost

From a 72-task `k8s-ai-bench` campaign (24 main tasks × 3 model tiers, one shared server, fresh kind cluster per tier, 222/222 usage footers price-verified):

```
kubectl apply          521
kubectl diff            87     <- one preview for every six apply attempts
validator delegations  198
validator model calls 2016     <- 44% of all agent calls, 40% of the bill
```

Per-call cost is near-uniform across agents ($0.0044–$0.0068), so the validator's share is **volume, not unit price**: a median of **25 validator calls per task**, **140** on the worst (`resize-pvc` on the `high` tier, $1.87 for one task).

The mechanism: a verdict is bound to the change's **content**, so every edit invalidates the previous one. Delegating before the manifest is settled buys a verdict the next edit throws away. The observed loop is apply → refused → delegate → apply.

`k8s_validator` is never named in the editor's instruction, so the refusal text — *"Delegate it to the k8s_validator sub-agent with the change identifier X"* — is the only thing teaching the agent the workflow.

## What commit 2 proposes

- **Step 7**: converge with `diff` first, then delegate **once**, then apply. States that a verdict follows the content, so an unchanged manifest keeps it.
- **Step 8**: a missing cluster capability is a terminal finding, not something to iterate against. `resize-pvc` is the case in evidence — no CSI resizer, and the agents iterate against it (140 / 92 validator calls, one timeout).
- **Verbatim values**: reproduce what the brief specifies. All three tiers wrote `image: nginx:latest` where the prompt said "nginx", which the upstream `create-pod` verifier string-matches and fails. That verifier is brittle and worth fixing upstream too, but silently re-specifying a named value is a defect on our side.

## A/B RESULT — commit 2's stated mechanism is falsified

Measured after the fact, single variable (same binary, same hook, same protocol, fresh kind cluster per arm), `deepseek-v4-flash-0731`, 24 tasks per arm:

| | baseline | with commit 2 | |
|---|---|---|---|
| `kubectl diff` | 29 | **66** | **+128%** |
| `kubectl apply` | 137 | 170 | +24% |
| validator delegations | 57 | **72** | **+26%** |
| validator model calls | 542 | 643 | +19% |
| tier cost | $4.03 | $4.37 | +8% |
| Pass@1 | 20/24 | 21/24 | +1 |
| timeouts | 2 | 1 | −1 |

**The instruction is obeyed — `diff` more than doubles — but the mechanism it claims does not happen.** Step 7 posits that converging with `diff` first cuts validator delegations. They rose 26%. If `diff` had displaced apply attempts the apply count would fall; it rose too. The preview phase was *added* to the apply→refuse→delegate loop, not substituted for it. Per task: delegations up on 9, down on 1, unchanged on 14.

The net outcome (+1 task, −1 timeout, +8% cost) is **within noise** at one run per arm — a single task out of 24 proves nothing. The robust signals are the behavioural counts, which rest on hundreds of events.

**So step 7 should not ship with the justification its commit message gives.** Reviewers should pick one: a follow-up that removes step 7, or one that keeps the wording and states only the measured effect. Commit `78cd667` is unaffected — it corrects statements that are false, verified command by command against a live cluster, and claims no quantified effect.

The likeliest explanation, and it moves the lever off the prompt entirely: if a delegation is triggered by the hook's refusal rather than by the agent's judgement, no instruction wording will reduce it. A cheap decisive test is in the report — instrument the hook to count `check_attested` refusals per task and compare with the delegation count.

Full analysis: `/home/bertrand/Documents/Dev/omnis-benches/reports/k8s-editor-instruction-ab-2026-09-06.md`

Two other findings from the same campaign are **not** addressed here and may deserve their own issues:

1. **The validator re-derives what the guard already computed.** The hook runs `kubectl diff` and a server dry-run and keeps the output in `preview`. `1c6aa48` already pipes attestation verdicts *into* the hook input; the reverse trip — injecting that `preview` into the validator's briefing — attacks the ~10 model calls each delegation costs. This multiplies with commit 2 rather than overlapping it.
2. **`k8s_validator` runs on `model_ref: high`.** It is a checker, not a planner, and on this suite `high` scored one task better than `deepseek-v4-flash` out of 22 discriminating tasks while costing 2.8×.

## Results

Full campaign data, protocol and the reserve on every figure:

- Report — protocol, per-task verdicts, cost breakdown, and the reserve on every figure:
  `/home/bertrand/Documents/Dev/omnis-benches/reports/deepseek-v4-flash-k8s-ai-bench-2026-09-06.md`
- Raw records — one JSON object per task: verdict, run order, per-agent calls and cost,
  `validator_tool_calls`, `blocked_by_ask_user`, `blocked_unattended`, `timed_out`:
  `/home/bertrand/Documents/Dev/omnis-benches/reports/deepseek-v4-flash-k8s-ai-bench-2026-09-06.jsonl`
- The two invalidated passes, kept as evidence of the bugs this branch fixes:
  `/home/bertrand/Documents/Dev/omnis-benches/reports/omnis-k8s-validator-starvation-2026-09-05.md`
  `/home/bertrand/Documents/Dev/omnis-benches/reports/deepseek-v4-flash-k8s-ai-bench-2026-09-05.md`
- Hook timing trace (65 invocations, 4.4 s total — the guard itself is not the cost):
  `/home/bertrand/Documents/Dev/omnis-benches/reports/omnis-k8s-hook-trace-2026-09-05.jsonl`

Reproduce:

```bash
cd omnis-benches/k8s-ai-bench
OMNIS_NON_INTERACTIVE=1 TASK_PATTERN='^[^g]' CONCURRENCY=1 ./run.sh
```

Then count, over the run's `log.txt` files: `kubectl diff`, `kubectl apply`, and `[tool] k8s_validator`.

## Context from the same campaign

Two earlier passes of this suite were invalidated before this one produced usable numbers, and both causes are now fixed in this branch — recorded here so the results are read against the right build:

- A `max_instances` semaphore shared across sessions starved `k8s_validator` after the first few tasks; every later mutating task timed out at 10m with zero validator calls. Fixed by the per-session semaphore (`3b5dd17`).
- 11 tasks were blocked by hook escalations nobody could answer in an unattended run. Fixed three ways — `CONTAINER_ACCESS_VERBS` for `exec`/`attach`/`cp`, the missing-namespace advice on a failed `diff`, and `OMNIS_NON_INTERACTIVE`. The current pass records **0 escalations over 72 tasks**, and the env var never had to fire because the first two removed the refusals upstream.
