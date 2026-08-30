# squad-bench — benchmark omnis squads across models and tasks

A dependency-free (Python stdlib) harness that drives a **running omnis-server**
through its HTTP API the same way the web UI does — create a session pinned to a
squad, send one task prompt, stream the SSE — and reduces the event stream to a
**metrics record**. The point: change which **model** an agent runs on and re-run
the **same task** to see the effect on cost, latency, delegation behaviour, and
correctness. Sister tool to [`model-probe`](../model-probe) (which checks a
raw endpoint's capabilities); this one checks *squad behaviour*.

## Why this exists

While turning the Coding squad multi-agent (a `premium` leader that delegates
search to a cheap `code_scout` and docs to `code_docs`), a live test showed the
wiring worked but surfaced two model-level facts that only a repeatable benchmark
can track over time:

- the **`simple`** model backing `code_scout` was slow enough that one search
  dispatch hung ~**310 s** and tripped the HTTP client read timeout
  (`context deadline exceeded … while reading body`), returning an empty result —
  so the `premium` leader re-dispatched, and the turn ran away;
- **`premium`** returned answers in **2–3 coarse chunks** where `hosted` streamed
  **~750** token events for a comparable answer — i.e. premium wasn't streaming
  token-by-token.

Rather than eyeball these once, `bench.py` measures them every run.

## Run it

```bash
# server must be running (default http://127.0.0.1:8080; set OMNIS_SERVER_TOKEN if auth is on)
python3 squad-bench/bench.py --suite                 # all tasks in tasks.json
python3 squad-bench/bench.py --task search-single    # one task
python3 squad-bench/bench.py --suite --repeat 3       # 3 samples each (models are stochastic)
python3 squad-bench/bench.py --suite --out runs.jsonl # append a JSON record per run
python3 squad-bench/bench.py --task search-single --json   # machine-readable only
```

Flags: `--server`, `--token`, `--deadline <s>` (per-turn cap, default 420 —
a multi-turn task gets `deadline` seconds for EACH turn, not for the whole
run), `--cwd <dir>` (override a task's working dir), `--keep` (don't delete
the bench session), `--tasks <file>`.

## The benchmarking loop (models × tasks)

1. Establish a baseline: `bench.py --suite --out baseline.jsonl`.
2. Change **one** agent's model — Settings → Agent → model, or edit `models.json`
   / `registry/agents/<name>/agent.json` and `POST /api/config/reload` (model
   changes hot-reload; embedder identity needs a restart).
3. Re-run the same suite: `bench.py --suite --out variant.jsonl`.
4. Compare the JSONL records. Each carries a `models` block keyed by agent with
   the **price** that was active (price is the model's identity here), so you can
   tell which model produced which numbers.

The same loop tunes **instructions**, not just models (see "Tuning prompts on
weak models" below): change the agent's `instruction.md`, reload/reinstall, re-run.

## Metrics (per run)

| Field | Meaning |
|---|---|
| `status` | `done` / `timeout` / `cancelled` / `error` |
| `wall_ms`, `ttfb_ms` | total time; time to first `token`/`message` frame |
| `token_events` | # of streamed `token` frames — **high ⇒ streams token-by-token; 1–3 ⇒ coarse/buffered/non-streaming** |
| `delegations` | `{agent: count}` the leader delegated to (a sub-agent tool call) |
| `redispatches` | # of times the leader called the **same** sub-agent again (retry / flailing) |
| `leader_tools` | `{tool: count}` the leader ran directly |
| `subagent_tools` | `{agent: {tool: count}}` each sub-agent ran internally (e.g. a scout doing 12 greps = over-searching) |
| `models` | `{agent: {in$/M, out$/M, prompt_tok, out_tok, cache_read_tok, calls, est_cost_usd}}` — see the cache-billing note below |
| `total_cost_usd` | summed estimate across all agents in the turn |
| `subagent_errors` | sub-agent results that were empty or carried an error (`deadline exceeded`, `timeout`, `"error"`) |
| `ask_user` | # of permission prompts (want **0** for a squad whose read-only members are allow-listed) |
| `correct` | if the task has `expect`, whether the final answer matched |
| `quality_gate` | layer-1 verdict: every `required` fact found **and** no `forbidden` rule hit. `null` when the task declares neither. |
| `facts` | `{found[], missing[], required, optional_found[]}` from the task's `facts` list |
| `forbidden_hits` | ids of `forbidden` rules violated (a match carrying its `unless` hedge is not a violation) |
| `fetches` / `distinct_urls` | `WebFetch` calls, and how many distinct URLs were fetched — an **efficiency** signal (same facts with fewer fetches is strictly better), not a quality one |
| `facts_per_fetch` | `len(facts.found) / fetches` |

## Tasks

Defined in [`tasks.json`](tasks.json). `cwd: "sandbox"` runs against a **fresh temp
copy** of [`sandbox/`](sandbox) (a tiny Go module, git-seeded and isolated, so an
accidental edit can never touch a real repo and is trivially reverted). `expect`
is a substring or `/regex/` (case-insensitive) matched against the final answer.

Shipped tasks: `search-single` (one-target search — measures scout over-search /
redispatch), `search-multi` (parallel fan-out over two targets), `symbol-fields`
(precise symbol read), `docs-lookup` (network — `code_docs` web research; skip
offline). Add your own with the same shape — a good bench grows a task per
behaviour you care about.

## Tuning prompts on weak models

A cheap model (e.g. `simple`) that "gets lost" — over-searching, not stopping,
returning empty — is usually a **prompt** problem before it's a model problem.
Bench the weak model, tighten the agent's `instruction.md` into a literal
numbered procedure with explicit **stop conditions** (see `code_scout`'s
instruction: one search at a time, stop as soon as found, hard cap on searches),
re-run, and watch `subagent_tools` grep counts and `redispatches` drop. Prompts
hardened against a dumb model tend to run even better on a smart one — so this is
worth doing *before* reaching for a pricier tier.

## Variant campaigns

`campaign.py` runs several config variants against the same task suite and writes
one JSON record per run, tagged with `variant` and `phase`.

```bash
set -a; . ./.env; set +a
python3 squad-bench/campaign.py --variants V0,V1,V3,V3b --repeat 2 \
    --tasks squad-bench/tasks-web.json --out campaign.jsonl
```

Variants live in `variants.json` and are applied over the omnis config API
(`PUT /api/config/parsed/<section>` + `POST /api/config/reload`), always from the
V0 snapshot so they never stack. Each apply is read back and **verified**; the
campaign always **reverts** in a `finally` block and reports whether the revert
round-tripped.

**Variants are interleaved in time** (V0,V1,V3, V0,V1,V3 …) and V0 is run once
before and once after the campaign as a **drift witness**. The web moves: running
all of V0 then all of V3 would confuse page drift with variant effect. If the
closing witness regressed in quality, or its median cost more than doubled, the
campaign exits non-zero and its numbers must be discarded.

**Every completed run is also checked for search-backend degradation**, post-hoc
(not as a pre-flight probe — the fleet runs on a paid Serper backend, so probing
e.g. DuckDuckGo directly would measure the wrong thing). A record is flagged
`search_degraded` when either its `subagent_errors` contain a search-failure
marker (`deadline exceeded`, `timeout`, `non-functional`, `rate limit`, `429`,
`no results` — case-insensitive), or its `fetches` count sits more than 3x away
from the median of its **same-task, same-variant** peers in the campaign (scoped
to the same variant too, so a variant that legitimately fetches fewer times by
design — e.g. one that delegates fetching to collapse an F² term — is never
penalized for doing its job). Degraded records are kept in the JSONL (nothing is
discarded) but excluded from the end-of-campaign medians; the exclusion count is
printed alongside the numbers it affects.

**The end-of-campaign summary always prints a median WITH its spread** — a
min-max range and the run count, per variant — never a bare median or a bare
"variant X is N% cheaper" without the ranges beside it. This is not cosmetic:
two runs of the **identical** configuration were measured to differ by **1.85x
in cost** ($0.908 vs $1.682) and **1.5x in fetches**, so a variant difference
smaller than the observed spread is not evidence of anything. When a baseline
(`V0`) is available, each other variant's line also notes whether its range
overlaps the baseline's — an overlap means the two are not distinguishable from
noise at this sample size.

## Notes / limits

- One run is one sample; models are stochastic. Use `--repeat` and compare
  distributions, not single numbers.
- Costs are **estimates** from the per-model prices in `models.json` (the same
  numbers the web UI shows), not a provider invoice.
- **Cached tokens are billed once, at the cache-read price — never double-charged.**
  `prompt_tokens` follows the OpenAI usage convention and already **includes**
  `cache_read_tokens` as a subset, not an addition (`cache_read_tokens` is a
  sub-field of the same usage record `prompt_tokens` comes from). `note_model`
  therefore bills only the *uncached* remainder (`prompt_tok - cache_read_tok`,
  clamped at zero) at the full input price; `cache_read_tok` pays the (usually
  much cheaper) cache-read price; `out_tok` pays the output price. Billing the
  full `prompt_tokens` **and** `cache_read_tokens` both at their own price — the
  pre-fix behaviour — double-charges the cached portion.
- **JSONL records written before this fix carry an inflated `est_cost_usd` /
  `total_cost_usd`** for any agent whose `cache_read_tok` is non-zero (a
  record with `cache_read_tok: 0` is unaffected and needs no correction).
  Existing files under `reports/` and any run captured before this change are
  affected and are **not** modified by it. Such a record can be recomputed from
  its own retained fields — for each agent in its `models` block:
  `uncached = max(0, prompt_tok - cache_read_tok)`;
  `corrected_cost = uncached*in_per_m/1e6 + cache_read_tok*cache_read_price_per_m/1e6 + out_tok*out_per_m/1e6`
  (the record does not persist `cache_read_price_per_m` per agent today, so
  recomputing a specific old record needs that price looked up from the
  `models.json` version active at the time it was captured). Do not treat a
  pre-fix and a post-fix record as directly comparable for a caching agent.
- Endpoint latency (e.g. the `simple` 310 s outlier) is a property of the gateway
  deployment, not of omnis — but it's exactly what you want a benchmark to catch.
