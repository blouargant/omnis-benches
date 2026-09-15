## Summary

The `k8s_validator`'s job is to re-derive a proposed change's effect from the live cluster. A dry run is the tool for that: it renders the manifest, runs admission, and writes nothing. **It was refused anyway** — and the reviewer then re-derived the same state by hand through a series of `get -o jsonpath` calls.

This PR admits the reviewer's dry runs. It is a **correctness fix, not a performance one** — see "What this does not claim", which retracts an earlier cost figure of mine.

| commit | what |
|---|---|
| `c76a123` | the reviewer may dry-run; `--dry-run=none` and bare `--dry-run` stay refused |
| `c21276d` | corrects step 7 of `k8s_editor/instruction.md`, whose claimed mechanism the A/B falsified |

## The defect

`VALIDATOR_AGENTS` is checked at the top of `validate()`, before any per-verb branch. So every dry run from the reviewer came back as:

```
The reviewer agent may not make changes to the cluster, only review them.
Run this command as the agent that requested the review, not as k8s_validator.
```

Probed directly against the shipped hook:

| command, as `k8s_validator` | before | after |
|---|---|---|
| `kubectl apply --dry-run=client -f m.yaml` | **deny** | allow |
| `kubectl apply --server-side --dry-run=server -f m.yaml` | **deny** | allow |
| `kubectl create --dry-run=server -f m.yaml -o name` | **deny** | allow |
| `kubectl apply -f m.yaml` (real) | deny | deny |
| `kubectl apply --dry-run=none -f m.yaml` | deny | deny |
| `kubectl apply --dry-run -f m.yaml` (bare) | deny | deny |
| `kubectl diff -f m.yaml` | allow | allow |

The refusal is wrong on the facts — a dry run persists nothing. Seen live in a hook trace, the reviewer opens almost every review by trying `apply --dry-run=server`, then `create --dry-run`, then `apply --dry-run=client`, is refused three times, and falls back to reconstructing the state with reads.

## The security property is preserved by placement, not by trust

`validate()`'s own comment explains why the reviewer check sits first: so that **nothing about the change — least of all its subject — is ever computed or disclosed to the reviewer**, because a reviewer that learns the change identifier can sign its own work. That is the property, and it is worth keeping.

A dry run does not need the subject. So the admission goes in `main()`'s segment loop, **before `validate()`** — the same place `provably_read_only()` already `continue`s from. An admitted dry run therefore never reaches `subject_hash`, and a real mutation from the reviewer still falls through to the identical identifier-free refusal.

The two negative cases are deliberate, and follow the guard's own doctrine of proving rather than guessing: `--dry-run=none` is a real apply wearing the flag, and a bare `--dry-run` is the deprecated boolean spelling whose meaning depends on the client version. Both stay refused.

Six new tests pin all of it, including that the admission is reviewer-only — another agent's dry run still goes through the ordinary chain, because for them it is a step toward a real apply that a verdict has to cover. Full `packaging` suite green (17 s); `./agent/... ./core/permissions/... ./server/...` green.

## What this does NOT claim — a retraction

An earlier revision of this PR claimed **−45 % validator delegations and −24 % cost**, measured on a 4-task probe. **That does not replicate**, and a control run shows why nobody could have known from a single arm.

The full 24-task suite was run twice on the built binary with this fix installed — **the same binary, hook, instruction and model override both times**, verified file by file before each launch. Paired over the 21 tasks that produced a usage footer in both:

| | run 1 | run 2 (identical config) | |
|---|---|---|---|
| cost | $3.98 | $4.35 | +9 % |
| validator delegations | 66 | 56 | **−15 %** |
| validator model calls | 602 | 542 | −10 % |
| `kubectl diff` | 75 | 53 | **−29 %** |
| `kubectl apply` | 183 | 118 | **−36 %** |
| Pass@1 | 19 | 19 | 0 |

Nothing changed between those two columns, and **5 of 24 verdicts still flipped** (`create-pod`, `fix-pending-pod`, `fix-service-routing`, `resize-pvc`, `statefulset-lifecycle`). Per-task durations swing the same way: `debug-app-logs` 297 s → 88 s, `scale-deployment` 63 s → 156 s.

So this suite cannot resolve an effect below roughly **1.4× on behavioural counters, or ±2 tasks on Pass@1, at k=1** — and the 4-task probe's headline sat far under that. It established that the code path activates; it could never have sized the gain.

The fix *is* active on the built binary — probed directly, the three reviewer dry-run spellings are admitted while the real apply, `--dry-run=none` and the bare `--dry-run` stay refused. This is not an inert patch. Its effect is simply not measurable at suite scale.

Pairing matters too: a task killed by the harness produces no footer and contributes **$0**, so the run that stalls most looks cheapest. The raw "−9 %" from run 1 was entirely that artefact.

So the case for this PR is that the refusal is factually wrong and costs the reviewer turns it should not spend — not a number.

## Commit 2: a correction of my own earlier claim

`2cb223c` (already on `feat/k8s-change-validation`) asserted that making the editor converge with `diff` first would cut validator delegations. Measured, one variable, 24 tasks per arm:

```
kubectl diff            29 ->  66   (+128%)
kubectl apply          137 -> 170   ( +24%)
validator delegations   57 ->  72   ( +26%)
```

Delegations rose. So did apply attempts, while diff more than doubled — the preview phase was **added** to the loop, not substituted for it. Per task: up on 9, down on 1, unchanged on 14.

Read against the identical-config control above, only half of that survives: `diff` ×2.28 clears the ×1.41 same-config swing, so the instruction is demonstrably read and applied; delegations ×1.26 does **not** clear ×1.18, so the +26 % should not be quoted as a fact. What holds either way is the negative: delegations did not fall. The instruction was obeyed; its stated mechanism is unsupported.

What is load-bearing is the **content binding**, so step 7 now states that and the two things that genuinely follow, and drops the unachieved imperative. The second half is newly measured: an attestation for a manifest does not cover the equivalent imperative command — observed live, the editor reviewed a manifest, applied via `kubectl scale`, and was refused for a subject it had never had reviewed.

## A separate finding worth its own issue: the stall guard can never fire under a 10-minute task budget

Not addressed by this PR, but found while validating it. `core/llm/stall.go` sets `defaultStreamStallTimeout = 10 * time.Minute`. Any harness or caller that also allows 10 minutes per task kills the process first, so the guard's own clear message — *"The session has been running for too long without an update"* — is unreachable, and a frozen upstream stream reads as an unexplained 10-minute hang with no accounting.

Three tasks in the validation run ended that way. All three logs stop mid-turn right after the leader announces a delegation; the server-side access log confirms a `POST /messages` still in flight with `turns: 1`. On re-run they pass.

10 minutes of total silence before a session gives up is also a long time for an interactive user, not only for a bench. Worth considering a lower default, or at least surfacing a "still waiting on the model" signal well before the abort. The bench side now sets `OMNIS_LLM_STREAM_STALL_TIMEOUT=120s` so the guard lands inside the task budget and the failure is named.

## What this does not fix

- **Heredocs.** `kubectl apply -f - <<EOF` is still unvalidatable and still costs the agent a turn to discover. It has a test marking it a known limitation; worth its own issue.
- **`create-pod`'s verifier** string-matches `nginx`, so `nginx:latest` fails. Upstream task defect, not ours — but the validation layer made every model write the explicit tag, by pushing them from imperative commands to manifests.
- **The ~10 model calls per delegation.** The obvious next lever is to hand the reviewer the `preview` the hook has already computed rather than have it derive one. Given the noise floor above, that should be measured over repeats, not a single arm.

## Reproduce

```bash
cd omnis-benches/k8s-ai-bench
OMNIS_SYSTEM_CONFIG_DIR=<copy of /etc/omnis> \
OMNIS_NON_INTERACTIVE=1 TASK_PATTERN='^[^g]' CONCURRENCY=1 ./run.sh
```

Then count, per task's `log.txt`: `[tool] k8s_validator` for delegations, and the `omnis-agent: usage` footer for per-agent calls and cost. Compare only tasks that produced a footer on both sides.

## Data

- Suite-scale validation of this fix, the identical-config control run, and the retraction above:
  `/home/bertrand/Documents/Dev/omnis-benches/reports/k8s-reviewer-preview-armC-2026-09-06.md`
  with `deepseek-v4-flash-k8s-ai-bench-2026-09-06-armC.jsonl` and `…-armC2.jsonl`
- A/B of the instruction change: `/home/bertrand/Documents/Dev/omnis-benches/reports/k8s-editor-instruction-ab-2026-09-06.md`
  and `k8s-editor-instruction-ab-2026-09-06.jsonl` (2 arms × 24 tasks)
- The campaign this all came out of: `/home/bertrand/Documents/Dev/omnis-benches/reports/deepseek-v4-flash-k8s-ai-bench-2026-09-06.md`
- Earlier invalidated passes, kept as evidence of the bugs already fixed on this branch:
  `/home/bertrand/Documents/Dev/omnis-benches/reports/omnis-k8s-validator-starvation-2026-09-05.md`
