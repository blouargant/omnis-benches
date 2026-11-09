# Collection memory — does a correction stick? (2026-11-09)

omnis `develop` at 240711f (collection memory: `memory_save` / `memory_read` /
`memory_delete` on every answering squad root, the collection's memory injected
every turn). Harness: `squad-bench/memory_bench.py` + `tasks-memory.json`, one
omnis-server per tier (`setup-ab.sh` with `MODEL=ref:<tier>`, i.e. the
single-model override forces that catalogue model onto every agent, router
included), 5 scenarios × 3 samples per tier, each scenario in fresh collections,
empty working directory. Raw records: `collection-memory-2026-11-09.jsonl`.

## Result

| Tier | Scenarios passed | Cost | Timeouts (420 s/step) |
|---|---|---|---|
| hosted | 10/15 | $0.04 | 2 |
| balanced | 8/15 | $0.60 | 2 |
| high | 7/15 | $0.72 | 2 |
| premium (Sonnet 5.5) | **13/15** | $1.88 | 0 |

Total $3.25, ~31 min wall clock (tiers in parallel).

| Scenario | hosted | balanced | high | premium |
|---|---|---|---|---|
| correction (a correction given once is applied in a NEW session) | 1/3 | 0/3 | 0/3 | 3/3 |
| explicit ("retiens que …") | 3/3 | 2/3 | 0/3 | 2/3 |
| update (a later correction replaces the value, no duplicate) | 2/3 | 1/3 | 2/3 | 3/3 |
| forget ("oublie …" deletes the memory) | 1/3 | 3/3 | 2/3 | 2/3 |
| no-pollution (an ordinary question writes nothing) | 3/3 | 2/3 | 3/3 | 3/3 |

**Isolation held everywhere:** no run leaked a memory into the other collection
(every `answer_not` check on the other-collection session passed), and no-pollution
wrote nothing in 14/15 runs (the one balanced failure is a wrong answer, not a
stray memory).

## What fails

1. **Weaker models do not save a correction.** On the `correction` scenario
   balanced and high applied the correction in the same turn (rewrote the commit
   message with the `[search-svc]` prefix) but never called `memory_save` — 0/6.
   Premium saved it 3/3. This is the scenario the feature exists for.
2. **"C'est noté, je m'en souviendrai" without saving.** high answered twice that
   it had memorised the test database name without calling the tool — the
   worst failure mode (the user believes it is remembered). Seen 2× in 36 first
   turns of the remember-type scenarios.
3. **When saved, recall works.** Every failed `step2/3_answer` in explicit/update
   follows a missing save; a saved `project` memory was found through the index +
   `memory_read` (balanced/hosted B sessions call `memory_read` before answering).
4. **Bench artefact (fix before re-running):** the cache-busting tag appended to
   each prompt, `(run 1d8a19da)`, reads like a commit reference: in ~5 steps the
   agent went hunting for that commit in the (empty) working directory and asked
   which repository to use. It muddies the `correction` scenario for every tier.
   The tag is not needed — each run's collection name already differs, and the
   collection name is in the system prompt.
5. Timeouts (6 steps, never premium): long tool explorations of the empty
   working directory on Coding-squad routes; not memory-related.

## Decision

The spec's catch-up pass (step 4) is warranted for the non-premium tiers, unless
tuning the injected rules first closes the gap. Next, cheapest first:

1. Drop the nonce tag from `memory_bench.py`, re-run `correction` + `explicit` on
   balanced and high (≈ $0.30) as the baseline.
2. Tune `collmem.Rules` on balanced/high: put the correction trigger first, and
   forbid claiming to remember without calling `memory_save`. Re-run.
3. If corrections are still missed, build the catch-up pass (idle session → one
   cheap model call over the user's messages + current index → proposed
   `memory_save` calls applied with chips).

## Tuning (same night) — `tune-memory-rules`

Raw records: `collection-memory-2026-11-09-tuning.jsonl`. The run tag was
removed from the prompts first (`memory_bench.py`), so every arm below is free
of the commit-hunt artefact.

| Arm | balanced | high |
|---|---|---|
| baseline: develop 240711f, no tag (correction + explicit) | 1/6 | 1/6 |
| v1: imperative rules (MUST save a correction before answering; never claim "noted" without saving) + `memory_save` description | 0/6 | 5/6 |
| v2: v1 + EVERY memory type inlined (project/reference were index lines only) | 2/6 | 5/6 (one run: 77 `memory_save` calls in one turn, $0.95) |

The two remaining causes, read from the transcripts:
- a `project` memory injected as an index line was answered by its **name**
  ("integration-test-db") instead of its content → v2 inlines every body,
  demoting reference/project before feedback/user over the budget;
- the imperative rule re-fired after each save (the block changes, the user
  message still is a correction) → v3 adds "save each subject once, then
  answer" and a host-side cap of 5 memory writes per turn.

**v3, full suite (5 scenarios × 3):**

| Tier | first run | v3 | cost first → v3 |
|---|---|---|---|
| balanced | 8/15 | **13/15** | $0.60 → $0.60 |
| high | 7/15 | **15/15** | $0.72 → $0.74 |
| premium | 13/15 | **14/15** | $1.88 → $1.89 |

Max memory writes in one scenario run: 3; no timeouts. Remaining failures:
balanced missed one correction save (1/3 correction runs) and one arithmetic
answer; premium's forget run deleted the memory but its answer still named
"Linear" (it said it had been told to forget it — the check is strict).

**Decision:** ship v3. In production every answering root except Helper runs on
premium, where v3 is at least as good. The catch-up pass (spec step 4) is not
needed for premium/high; it would only serve balanced (Helper) — not worth
building for now.
