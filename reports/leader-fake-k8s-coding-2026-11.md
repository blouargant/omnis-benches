# Kubernetes and Coding leaders vs scripted sub-agents (2026-11-23)

Same method as `leader-fake-2026-11.md` (System leader): the squad's sub-agents
answer from a script (`squad-bench/fake_subagents.py`), only the leader runs on
a real model — `balanced`, then `premium` (Sonnet 5.5). omnis `develop` at
`db28817`. How to run: `squad-bench/README-leader-fake.md`.

Three samples per cell: read the counts as indications, not rates.
Cost of everything below: **$2.14** for 84 runs.

| Records | Content |
|---|---|
| `leader-fake-2026-11-k8s-{balanced,premium}.jsonl` | Kubernetes, 5 scenarios |
| `leader-fake-2026-11-coding-{balanced,premium}.jsonl` | Coding, first run (docs on an internal library) + `cd-review` |
| `leader-fake-2026-11-coding-docs-{balanced,premium}.jsonl` | Coding docs scenarios, re-run on public libraries |

## Kubernetes (`k8s_leader`)

The evidence is on a cluster the prompt says only `k8s_investigator` can reach
(`prod-eu-2`); `k8-unprompted` asks about the current cluster and names no one.

| Scenario | Leader | Delegated | `k8s_investigator` calls | Answer correct |
|---|---|---|---|---|
| `k8-unprompted` | balanced | 3/3 | 1, 2, 2 | 3/3 |
| | premium | 1/3 | 0, 1, 0 | 3/3 |
| `k8-good` | balanced | 3/3 | 1, 1, 1 | 3/3 |
| | premium | 3/3 | 1, 1, 1 | 3/3 |
| `k8-fanout` | balanced | 3/3 | 2, 2, 2 — in parallel 3/3 | 3/3 |
| | premium | 3/3 | 2, 2, 2 — in parallel 3/3 | 3/3 |
| `k8-empty` | balanced | 3/3 | 4, 3, 2 | 3/3 |
| | premium | 3/3 | 2, 2, 2 | 3/3 |
| `k8-reword` | balanced | 3/3 | 2, 2, 2 | 3/3 |
| | premium | 3/3 | 2, 2, 2 | 3/3 |

- **On Kubernetes, `balanced` delegates unprompted (3/3) and fans out (3/3).**
  In the System squad the same model did neither (0/15 and 0/3). The
  `k8s_leader` instruction spells both rules out at length ("your job is to
  coordinate, not to execute", "one k8s_investigator call per INDEPENDENT
  evidence question, several in the same response"). The System failure is
  therefore largely an instruction problem, not a model limit.
- **`premium` used its own `kubectl` when no sub-agent was named** (2 of 3). It
  then tried the kubeconfig contexts of the bench host, read-only, and reported
  it could not reach a cluster holding the namespace.
- **Empty evidence:** `premium` stops after two calls (3/3); `balanced` makes
  two to four. The instruction says "2-3 times before taking over yourself".
- One `balanced` fan-out run also called `k8s_cleaner` (step 7, "sweep
  leftovers") although nothing had been created.

## Coding (`coder`)

### Documentation lookups

The coder has no web tool, so `code_docs` is its only source for a library it
does not know; no prompt names it. Libraries are fictional and public
(`github.com/kestrelworks/…`).

| Scenario | Leader | Delegated | `code_docs` calls | Answer correct |
|---|---|---|---|---|
| `cd-docs` | balanced | 3/3 | 1, 1, 1 | 3/3 |
| | premium | 3/3 | 1, 1, 1 | 3/3 |
| `cd-fanout` | balanced | 2/3 | 0, 2, 2 — in parallel 2/2 | 2/3 |
| | premium | 3/3 | 2, 2, 2 — in parallel 3/3 | 3/3 |
| `cd-empty` | balanced | 3/3 | 2, 2, 2 | 3/3 |
| | premium | 3/3 | 1, 1, 1 | 3/3 |
| `cd-reword` | balanced | 3/3 | 5, 2, 2 | 3/3 |
| | premium | 3/3 | 2, 2, 2 | 3/3 |

- **Both models delegate documentation lookups and fan out.** The "coder never
  delegates" seen in the Harbor smokes does not hold for docs it cannot know.
- **`premium` judges whether the teammate can help.** In the first run the
  libraries were on an internal GitLab host: `premium` did not delegate in 12 of
  12 runs and said why — "a public web search can't reach a private GitLab host,
  so Docs can't help here" — then explained how to get the signature. `balanced`
  delegated anyway (12/12). The scenarios were moved to public libraries.
- **One `balanced` run ended on leaked tool markup.** `cd-fanout` s1: the whole
  answer is `<tool_search> <tool_search>`, no tool call, cost $0. The model
  wrote a call to the coder's deferred-tool search as text. `llm.GuardToolText`
  does not catch this shape (it knows `<tool_call`, `<function=`,
  `<parameter=`), so the turn ended with the markup shown to the user.
- **Empty evidence:** `premium` stops after one call (3/3), `balanced` after two.

### Review loop (`cd-review`)

The coder edits `retry.go` in the sandbox copy and is asked to have its diff
reviewed. The scripted reviewer returns one blocker, then a clean pass.

| Leader | `reviewer` calls | What happened |
|---|---|---|
| balanced | 0, 2, 2 | two runs: review, fix, verification pass. **One run reported a review that never took place.** |
| premium | 1, 1, 1 | one review, acted on it, no second round — and says so |

- **`balanced` invented a review, 1 of 3.** With zero reviewer calls in the log,
  the answer lists "What the reviewer flagged" (four detailed points) and "What
  the reviewer confirmed". Nothing in the transcript distinguishes it from a
  real review.
- **`premium` keeps to "at most two rounds"** and skips the verification pass
  when it judges the blocker already handled; it states that it did not send
  its later fix back for review.
- **`premium` made every edit through `Bash`** (3 to 5 `Bash` calls, no `Edit`
  or `Write`) in all three runs.

## Across the three squads

| Behaviour | balanced | premium |
|---|---|---|
| Delegates when no sub-agent is named | System 0/15, Kubernetes 3/3, Coding docs 11/12 | System 2/3, Kubernetes 1/3, Coding docs 12/12 |
| Fans out two independent questions | System 0/3, Kubernetes 3/3, Coding 2/2 | 3/3 in all three |
| Calls on empty evidence | System 4-6, Kubernetes 2-4, Coding 2 | System 2, Kubernetes 2, Coding 1 |
| Recovers from an off-topic answer | yes, 9/9 | yes, 9/9 |

## Limits

- Three samples per cell.
- **No scenario asks for a cluster change.** The bench host has a live cluster
  and the arm runs with `bypassPermissions`; delegation of changes to
  `k8s_editor` is not measured.
- No scenario for `code_scout`: in a 34-line sandbox, searching it yourself is
  what the coder's instruction allows.
- `near_repeats` counts the two requests of a fan-out as near-repeats when they
  differ only by a library name (`cd-fanout`: 1 in most runs). It is a false
  positive there; no scenario gates on it for a fan-out.
- One `balanced` run called `memory_save` during `cd-reword`; not investigated.

## What to do next (omnis)

1. **System leader instruction.** Port the two passages that work on
   `k8s_leader` (coordinate-not-execute, one call per independent question) and
   re-run `tasks-leader-fake.json` on `balanced`. Cheap, and this bench measures
   the result.
2. **A review that never happened.** The host knows whether `reviewer` was
   called in the turn. Either the claim can be checked host-side, or the coder's
   instruction needs a rule like the memory one ("never say a review was done
   without calling the reviewer") — and a bench that catches the regression
   exists now.
3. **Leaked `<tool_search>` markup.** Add the deferred-tool shape to
   `GuardToolText`'s markers, or guard any `<name>` that is a declared tool.
4. **Empty-evidence rule.** Three leader instructions give three numbers (stop
   after two; re-task with different guidance; 2-3 times). `premium` settles on
   one or two calls everywhere. One rule, stated once, would do.
