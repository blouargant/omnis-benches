# `token_optimization` (Bash output filters): measured, then removed — 2026-09-25

**Question.** omnis's `token_optimization` switch ran every `Bash` tool result
through ~126 declarative filters (a port of the *snip* format) that condensed or
rewrote the output, and injected arguments (`git log -n 10`, `go test -json`,
`git diff --stat`…). Does it lower the cost of real turns?

**Answer: no.** The shipped filter set lowers accuracy and does not lower cost;
a lossless rewrite keeps accuracy but saves nothing measurable. The feature was
removed from omnis (branch `chore/remove-token-optimization`).

## Method

- **Offline replay** — 44 real commands (git / go / kubectl / helm / npm / pip /
  cargo / ls / find / ps…) run through omnis's own `RunBash` three ways (off,
  shipped set, lossless set), comparing what the model would receive.
- **Live A/B** — `campaign.py` against the running omnis-server, variants
  applied over the config API and interleaved in time, opening/closing V0
  witnesses. Tasks: [`squad-bench/tasks-tokopt.json`](../squad-bench/tasks-tokopt.json),
  variants: [`squad-bench/variants-tokopt.json`](../squad-bench/variants-tokopt.json),
  fixtures: [`squad-bench/setup-tokopt.sh`](../squad-bench/setup-tokopt.sh).
  - Round 1: 5 tasks × {V0, TO} × 4 reps (+ witnesses) — `token-optimization-r1-2026-09-25.jsonl`
  - Round 2: 9 tasks × {V0, TO, TL} × 3 reps (+ witnesses) — `token-optimization-r2-2026-09-25.jsonl`
- Variants: **V0** filters off · **TO** shipped set · **TL** lossless set from
  [`gen_lossless.py`](../squad-bench/gen_lossless.py) (no head/tail/truncate, no
  semantic arg injection, no filter at all on query commands, `keep_lines` only
  for installers, hand-written `go test` / `cargo test` keeping failures + counts).

## Offline replay

| | bytes to the model |
|---|---|
| off | 339,666 |
| shipped set | 43,929 (−87%) |
| lossless set | 338,351 (−0.4%) |

The −87% is almost entirely **truncation of the answer itself**:

| command | off → shipped | what was lost |
|---|---|---|
| `kubectl describe node` | 45,450 → 1,810 | `kubectl-get` matches *any* kubectl command, keeps 30 lines |
| `kubectl get deploy -A -o yaml` | 50,031 → 918 | same |
| `git diff HEAD~3` | 17,147 → 398 | `--stat` injected: no diff content |
| `git log` | 50,031 → 823 | `-n 10` injected |
| `go test` (1 failing) | 107 → 18 | `5 passed, 1 failed` — no test name, no message |
| `cargo test` (1 failing) | 753 → 26 | counts only |
| `npm ls` / `pip list` | 166 / 210 → 2 | `ok` |
| `git status` (clean) | 114 → 11 | `(no output)` |

The lossless set saves little because the big outputs are exactly the ones
whose content *is* the answer.

## Live results (round 2, campaign phase, 27 runs per variant)

| | V0 off | TO shipped | TL lossless |
|---|---|---|---|
| correct | 26/27 | **21/27** | 25/27 |
| runs aborted on a permission prompt | 0 | **5** | 0 |
| median prompt tokens | 34k | 44k | 37k |

Per task (round 2, correct / median Bash calls):

| task | V0 | TO | TL | note |
|---|---|---|---|---|
| npm-deps | 3/3 · 1 | **1/3** · 4 | 3/3 · 1 | `npm ls` → `ok`; agent tried `node -e …`, `cd … && npm list` → prompts |
| pip-ver | 3/3 · 1 | **0/3** · 5 | 3/3 · 1 | `pip list` → `ok`; agent tried `python -m pip list >/tmp/pip_out.txt` → prompts |
| k8s-pod-count | 2/3 · 7 | 2/3 · 15 | 1/3 · 3 | misses are the model miscounting 160 rows — filter-independent (TL doesn't filter kubectl) |
| go-test-count | 3/3 | 3/3 | 3/3 | TO −37% prompt tokens: the one case where a summary genuinely helped |
| go-fail, rust-fail, git-*, k8s-node-alloc | all 3/3 | all 3/3 | all 3/3 | rust-fail: coder used `run_tests`, which was never filtered |

Round 1 (V0 vs TO only) agreed: total $1.84 vs $2.09, median prompt tokens 57k
vs 67k; on `git-diff-files` TO made 2.5× the Bash calls and tried `git diff … |
cat` to get past the filter.

## Why there is nothing to win

Even a one-command task carries ~16k prompt tokens — system prompt + tool
catalogue — before any Bash output. Output the agent needs cannot be removed
without it re-querying; output it doesn't need is rare, and runaway output is
already capped by omnis's 32 KB universal output shaper.

## Caveats

- **Dollar cost is unusable here.** It is dominated by prompt-cache hits:
  `git-nth` cost $0.015 vs $0.055 with *identical* token counts, and TL looked
  35% cheaper than V0 on tasks where it behaves byte-identically. This also made
  `campaign.py`'s cost drift witness void both rounds. Compare correctness,
  prompt tokens and tool-call counts instead.
- Small samples (3–4 reps per cell). The accuracy and re-query effects are
  large and consistent across reps; token deltas under ~20% are not evidence.
- Ground truth is pinned to omnis@f2b3cf7 and the test cluster's state that day.

## Harness changes made for this

- `variants.py`: a patch without `"agent"` sets a section-level key; `${VAR}` in
  variant values is expanded at load (fails loudly if unset).
- `bench.py`: `${VAR}` expansion in task `cwd`; `ask_detail` records *what*
  a permission prompt asked (which command to allow-list).
