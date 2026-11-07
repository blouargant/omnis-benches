# harbor/ — omnis as a harness under Harbor (Terminal-Bench 2.1, DeepSWE v1.1)

Runs omnis as a coding-agent **harness** on the two benchmarks of the
[Harness Leaderboard](https://joelniklaus-harness-leaderboard.hf.space)
(Space `joelniklaus/harness-leaderboard`), through
[Harbor](https://harborframework.com), so omnis can be compared with Pi,
mini-swe-agent, Claude Code… **same model, same tasks, same scoring**.

Two variants make the A/B that matters:

| Variant | What runs | Fixed tokens / model call (measured) |
|---|---|---|
| `full` | the shipped **Coding** squad: leader `coder` + `code_scout`, `code_docs`, `reviewer`, `refactorer`, `agentmd_reviewer`; coder tools `fs, softskills, planning, worktree, bg, lsp, tests, astgrep` | ~16.0k |
| `full-noreview` | `full` **minus the `reviewer`** (dropped from the squad, its paragraph cut from the coder instruction); everything else identical, so `full` vs `full-noreview` isolates what the reviewer buys | ~15.5k |

**Production tiering and squad shapes** (outside the leaderboard rules):
`TIERED=1` keeps the shipped `models.json` tiers (leader on `premium`,
sub-agents on their own models, all through the gateway) and prices each agent
at its own model; `-m` is then only a label. `SHAPE=<arm>` applies a
`squad-bench/shapes.json` arm (e.g. `coding-C` = without `reviewer` and
`code_scout`) as an overlay copied into the omnis user layer before the run.
Example: `TIERED=1 SHAPE=coding-B ./run.sh tb full smoke`.
| `lean` | **`coder` alone** (leaderless squad), tools `fs` + `tests` only, instruction stripped of the team / LSP / ast-grep sections | ~4.7k |

(For reference the leaderboard leaders carry ~2–3k: Pi has 4 tools,
mini-swe-agent a bash tool.)

## How it maps onto the leaderboard's method

The leaderboard installs each harness as a Harbor *installed agent*
(`hlb/harbor_ext/agents.py`, one class per harness, pinned versions in
`hlb/data/harnesses.json`), runs the task subsets of `hlb/data/benchmarks.json`
(task repos pinned to a commit), 3 attempts per task, binary resolve from the
task's verifier. This adapter does the same:

| Leaderboard | Here |
|---|---|
| `class: hlb.harbor_ext.agents:HFPi` … | `omnis_harbor.agent:OmnisAgent` (`--ak variant=full\|lean\|full-noreview`) |
| harness `version` pin | omnis built from a pinned git ref (`--ak omnis_ref=…`, default `HEAD` of `../omnis`), version recorded per trial |
| TB 2.1 @ `d49e28f1`, DeepSWE @ `0b9fabbb` | same commits (`fetch-tasks.sh`) |
| subsets smoke / pilot / full (seed 20261014) | same lists, copied into `subsets.json` |
| 3 attempts / task | `ATTEMPTS=3` (`harbor run -k 3`) |
| DeepSWE agent phase offline | Harbor applies the task's `no-network`; only the model gateway is allow-listed (`--allow-agent-host`) |
| model via HF router, one provider pinned | model via the gateway in the root `.env` (OpenAI-compatible) |
| tokens/cost from a metering proxy | tokens/cost from omnis's own event log (see limits) |

### What the agent does in the sandbox

* **install** (host side, cached): `build-omnis.sh` → `git archive <ref>` of the
  omnis checkout into a temp dir (the checkout itself is never touched) → static
  `CGO_ENABLED=0` linux binary. `make_sysconf.py` builds the **system config
  layer** from the same source tree: shipped `config/` + `registry/` +
  `softskills/`, with these overrides only:
  * `models.json`: one `openai_compat` provider whose `base_url`/`api_key` are
    the env-var **names** `OPENAI_BASE_URL`/`OPENAI_API_KEY` (no secret on disk);
    every tier aliased to the bench model + single-model override on, so leader
    and sub-agents all run on the one model (leaderboard rule); `max_output_tokens`
    set (default 32000 — without it some gateway models stop at ~5k output).
  * `permissions.json`: `bypassPermissions` (as `k8s-ai-bench/bench-permissions.json`).
  * `agents.json`: `start_squad: coding`, `router_squad: none` (never through the
    router), `turn_budget` 0/0 (no per-turn ceiling: the task timeout bounds the
    run, as for other harnesses), curator + reflector removed.
  * `hooks.json` removed (its only entry is the Kubernetes guard, `fail_closed`
    with python3 on every Bash call — it would block every Bash call in an image
    without python3).
  * `full-noreview`: the Coding squad without `reviewer` (members + coder instruction).
  * `lean`: Coding squad → leaderless `coder`, tools `fs`+`tests`, lean instruction.
  Binary + tree are uploaded to `/installed-agent/omnis-bench/`.
* **run**: `omnis -d < instruction.md` in the task's working directory with
  `OMNIS_SYSTEM_CONFIG_DIR=/installed-agent/omnis-bench/sysconf` (**never**
  `OMNIS_CONFIG_PATH`), `OMNIS_HOME=/logs/agent/omnis-home`,
  `OMNIS_NON_INTERACTIVE=1`, `OMNIS_START_SQUAD=coding`,
  `OMNIS_CURATOR_ENABLED=false`, `OMNIS_UPDATE_CHECK=false`,
  `OMNIS_AGENTSKILLS_DIR=` (no host plugins). The prompt is the task instruction
  **verbatim**, on stdin (an instruction starting with `-` can't become a flag;
  stdin is then at EOF so an `ask_user` gets "cancelled" instead of hanging).
* **post-run**: `omnis-home/logs/agent_events_*.log` (full payloads, `-d`) →
  `usage.py` → Harbor's `n_input_tokens` / `n_cache_tokens` / `n_output_tokens` /
  `cost_usd` + `metadata` (per-agent breakdown, model calls, tool calls). Also
  written to `agent/omnis-usage.json` in the trial dir.

## Install

```bash
uv tool install 'harbor==0.24.0'      # the leaderboard pins 0.24.0
docker compose version                # Harbor's docker env needs the compose v2 plugin
docker buildx version                 # optional — see below
go version                            # to build omnis (any Go that builds ../omnis)
```

DeepSWE's agent phase is offline; Harbor lets the model gateway through with an
egress-control **sidecar image** it builds with `docker buildx`. Without the
buildx plugin that build fails (`unknown flag: --file`) and every DeepSWE trial
is an infra error. `run.sh deepswe …` calls `prebuild-sidecar.sh`, which builds
the same image with the legacy builder under the exact content-addressed tag
Harbor looks for (dropping only the BuildKit-only `COPY --chmod`), so Harbor
skips its own build. No-op when buildx is installed.

Credentials: `OPENAI_BASE_URL` / `OPENAI_API_KEY` in the repo-root `.env`
(the single mechanism of this repo). Task images are pulled from Docker Hub /
ECR on first use (TB images are 1–10 GB each).

## Run

```bash
# smoke: the leaderboard's 3-task smoke subset, 1 attempt
harbor/run.sh tb      lean
harbor/run.sh tb      full
harbor/run.sh deepswe full-noreview      # A/B against deepswe full: what the reviewer buys
harbor/run.sh deepswe lean
harbor/run.sh deepswe full

# explicit tasks
harbor/run.sh tb lean fix-git,overfull-hbox

# THE FULL CAMPAIGN (expensive — ask before launching): 3 attempts × every task
ATTEMPTS=3 CONCURRENCY=4 harbor/run.sh tb      full full
ATTEMPTS=3 CONCURRENCY=4 harbor/run.sh tb      lean full
ATTEMPTS=3 CONCURRENCY=4 harbor/run.sh deepswe full full
ATTEMPTS=3 CONCURRENCY=4 harbor/run.sh deepswe lean full
# (or `pilot` = the leaderboard's 50-task pilot subsets, ~half the cost)

# re-summarise / merge jobs into a JSONL for a report
python3 harbor/summarize.py harbor/jobs/<job> [...] --jsonl reports/<name>.jsonl
```

Knobs: `MODEL` (default `openai/deepseek-v4.1-flash-scaleway` — the same model
family as the leaderboard's DeepSeek-V4.1-Flash), `IN_PRICE`/`OUT_PRICE`/
`CACHE_PRICE` ($/M, default that model's gateway prices 0.63/1.89/0.126),
`CONTEXT_LENGTH`, `ATTEMPTS`, `CONCURRENCY`, `OMNIS_REPO`/`OMNIS_REF`,
`JOBS_DIR`, `JOB_NAME`; any extra argument goes to `harbor run`
(e.g. `--agent-timeout-multiplier 2`, `--debug`).

Outputs: `harbor/jobs/<job>/<trial>/` (Harbor's `result.json`, `agent/omnis.txt`
= final answer, `agent/omnis.stderr`, `agent/omnis-home/logs/` = full omnis event
log, `verifier/`). `harbor view harbor/jobs` browses them.

Tests (pure logic, stdlib, no docker/model): `python3 -m unittest discover -s harbor`.

## Limits (read before comparing with the board)

* **Not the leaderboard's model route.** The board pins one provider on the HF
  router (GLM-5.3-Flash on zai-org, DeepSeek-V4.1-Flash on its provider, Flint on
  dedicated endpoints). Here the model goes through our LiteLLM gateway
  (`deepseek-v4.1-flash-scaleway` = Scaleway). Same weights family, different
  provider/serving → absolute scores are **indicative**; only the omnis
  `full` vs `lean` comparison is apples-to-apples. To compare with the board's
  numbers for real, point `OPENAI_BASE_URL`/`MODEL` at the same HF route.
* **Reasoning effort is not pinned.** The board pins `low`/`high` on every call
  through each harness's own option and enforces it in its proxy. omnis has no
  per-model effort setting, so the provider default applies.
* **Cost is harness-reported**, from omnis's event log, not an external meter.
  It covers every model call omnis makes (leader and sub-agents both emit
  `after_model`); calls made by anything else (none known) would be missed.
  Cost is computed from configured prices, not the gateway's bill.
* **No ATIF trajectory / atif-scan.** The board scans every trajectory for
  cheating (looking up solutions, fetching upstream code). Our trials keep the
  full omnis event log (every tool call and argument) for manual review, but no
  automatic scan is run. Note: TB tasks keep internet access (as on the board);
  omnis's Coding squad has no web tools on the leader, but `code_docs` (full
  variant) does web research.
* **Local docker, not HF Sandbox**: resources as declared by each task; images
  that need KVM (`qemu-*`, excluded by the board too) are left out of `full`.
* **Infra errors are not fails** (summarize.py reports them apart); the board
  retries then excludes them — use `harbor run --max-retries 2` for a campaign.
* **Gateway response cache**: the ChapsVision gateway caches identical requests
  (see ../CLAUDE.md). The first model call of each attempt is identical across
  attempts (same system prompt + instruction), so 3 attempts may share a cached
  first reply and be less independent than on the board. Later calls depend on
  tool output and diverge.
* `fail_closed` Kubernetes hook, curator/reflector and the per-turn budget are
  disabled (see above) — deliberate deviations from the shipped install, all
  irrelevant to coding tasks or replaced by the task timeout.
