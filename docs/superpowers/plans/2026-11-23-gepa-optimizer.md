# GEPA optimizer (omnis-benches) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `gepa/` tool in omnis-benches that evolves an omnis agent's texts
(instruction, `turn_reminder`, skills) with GEPA against the scripted squad-bench
suites, and ends each run with a held-out verdict, a report and a patch.

**Architecture:** `gepa.optimize` drives an `OmnisAdapter`. Each candidate is
written into a bench omnis-server's user layer and hot-reloaded; the tasks run
through `squad-bench/bench.py --json` as a subprocess against that server and a
private `fake_subagents.py`. A guarded proposer wraps GEPA's reflection prompt
and rejects proposals that drop a protected rule, leak bench facts or grow too
much. Part 1 of the spec (`prompt_overrides.json` in omnis) is a separate plan;
here `prompt:<id>` components are refused.

**Tech Stack:** Python 3 (stdlib) + `gepa==0.1.4`, pytest; the existing
`squad-bench/setup-ab.sh`, `fake_overlay.py`, `fake_subagents.py`, `bench.py`.

**Spec:** `../omnis/docs/superpowers/specs/2026-11-23-gepa-prompt-evolution-design.md`
(read it first; the training tasks are on branch `bench/gepa-train-tasks`,
merge it into the work branch at Task 1).

## Global Constraints

- Nothing imports omnis; the tool talks to omnis-server over HTTP only.
- Only dependency beyond stdlib: `gepa==0.1.4` (in `gepa/requirements.txt`).
- Search runs on the run's first model only; other models only on held-out.
- First run: search repeats 2, held-out repeats 5, dollar ceiling $60.
- Proposal length limit: +30 % characters over the **seed** text of that component.
- Feedback shown to the reflection model never contains fact match patterns,
  `forbidden` patterns or scripted replies.
- A reached agent without a suite ⇒ the run refuses to start, listing them.
- Adopt rule: per (agent, model) suite mean over repeats, 90 % bootstrap interval
  resampling repeats within tasks; adopt when no candidate mean falls below the
  baseline's interval and at least one rises above it.
- Keep-list check is on the whole candidate (a rule kept in any component that
  reaches the same agent counts as kept).
- Nothing is written to the omnis checkout; the patch is a file in the run output.
- The reflection model is omnis's `premium` catalogue model, the keep check uses
  `hosted`; both called on the gateway through `OPENAI_BASE_URL`/`OPENAI_API_KEY`
  (from `.env`), model ids read from `<omnis>/config/models.json`.

## Review Focus

1. **A reload that did not take** (build error, ignored override, same generation)
   must fail the evaluation loudly, never score the previous text — Task 6.
2. **Infrastructure failures are not agent failures**: a record with
   `fake_error`, or `status == "error"` (stream broken, gateway 5xx), is retried
   once and then dropped from the batch, not scored 0 — Tasks 3 and 7.
3. **A proposal with no fenced block, an empty text, or the identical text** is
   rejected like a guard failure (parent kept) — Task 5.
4. **Resume after a crash** keeps the dollars already spent in the ceiling
   (ledger in `run_dir`) — Task 5.
5. **French and non-ASCII texts** round-trip byte-exact through seed → candidate →
   overlay files (UTF-8, no trailing-newline drift) — Task 1.

---

### Task 1: Components — seed, apply, reach

**Files:**
- Create: `gepa/__init__.py` (empty), `gepa/components.py`, `gepa/requirements.txt` (`gepa==0.1.4`)
- Test: `gepa/test_components.py`

**Interfaces:**
- Produces:
  - `parse(name: str) -> tuple[str, str]` → `(kind, target)`, kind ∈ `instruction`, `turn_reminder`, `skill`, `prompt`; `ValueError` otherwise.
  - `read_seed(omnis_src: Path, names: list[str]) -> dict[str, str]` — from `config/` + `registry/` of the checkout. `prompt:*` ⇒ `NotImplementedError("prompt components need omnis prompt_overrides (spec part 1)")`.
  - `apply_candidate(home: Path, base_overlay: Path, candidate: dict[str, str]) -> None` — resets `home/registry` and `home/models.json` from `base_overlay` (the fake overlay), then writes each component; `turn_reminder` is merged into the overlay's `agent.json` (keeps `model_ref`); `skill` keeps the seed front matter and replaces the body.
  - `agents_reached(name: str, omnis_src: Path) -> set[str]` — `instruction`/`turn_reminder` ⇒ `{target}`; `skill` ⇒ agents whose `agent.json` `skills` lists it, plus agents with `Skill` in `tools` and no/empty `skills`.

- [ ] **Step 1: Merge `bench/gepa-train-tasks` into the work branch.** Run `git merge --no-ff bench/gepa-train-tasks`; expected: clean merge.
- [ ] **Step 2: Write failing tests** `test_parse_rejects_unknown_kind`, `test_seed_reads_instruction_and_reminder` (fixture omnis tree in `tmp_path` with `registry/agents/leader/{agent.json,instruction.md}`), `test_apply_merges_reminder_keeps_model_ref`, `test_apply_skill_keeps_front_matter`, `test_apply_resets_previous_candidate` (a component of candidate A absent from B is gone after applying B), `test_roundtrip_utf8` (`"Délègue — « vite »\n"` exact), `test_reach_skill_empty_list_means_all`, `test_prompt_component_not_implemented`.
- [ ] **Step 3: Run** `python3 -m pytest gepa/test_components.py -q` — expected FAIL (module missing).
- [ ] **Step 4: Implement `gepa/components.py`.** Files written with `encoding="utf-8"`, text written as given (no strip).
- [ ] **Step 5: Run** the same command — expected all pass.
- [ ] **Step 6: Commit** `gepa: components (seed, apply, reach)`.

### Task 2: Suites and split

**Files:**
- Create: `gepa/suites.json`, `gepa/suites.py`
- Test: `gepa/test_suites.py`

**Interfaces:**
- Consumes: `agents_reached` (Task 1).
- Produces:
  - `suites.json`: `{"<agent>": {"squad": str, "fake": [agents], "train": [task files], "val": [task files], "heldout": [task files]}}` — `leader`: squad `system`, fake `investigator,summariser,helper,linux_admin`, train `tasks-leader-fake-train.json`, val `tasks-leader-fake.json`, heldout `tasks-leader-real.json`,`tasks-leader-fake-direct.json`; `k8s_leader`: `kubernetes`, fake `k8s_investigator,k8s_editor,k8s_cleaner`, train `tasks-leader-fake-train-k8s.json`, val `tasks-leader-fake-k8s.json`, heldout `[]`; `coder`: `coding`, fake `code_scout,code_docs,reviewer,refactorer,agentmd_reviewer`, train `tasks-leader-fake-train-coding.json`, val `tasks-leader-fake-coding.json`, heldout `[]`.
  - `@dataclass Item(agent: str, task_file: str, task_id: str, task: dict)` (task files relative to `squad-bench/`).
  - `load(agents: set[str]) -> dict[str, dict]` — raises `MissingSuites(sorted names)` when an agent has no entry.
  - `items(agents, split: str) -> list[Item]` for `train`/`val`/`heldout`.
  - `fake_agents(agents) -> list[str]` — union of their `fake` lists, sorted.
- Note: an agent with empty `heldout` gets no held-out verdict; the run config must list it in `heldout_ok_missing` or the run refuses (`MissingSuites`).

- [ ] **Step 1: Write failing tests** `test_missing_suite_lists_agents`, `test_items_train_ids_from_file`, `test_fake_union_sorted`, `test_empty_heldout_refused_unless_allowed`.
- [ ] **Step 2: Run** `python3 -m pytest gepa/test_suites.py -q` — expected FAIL.
- [ ] **Step 3: Implement** `gepa/suites.json` and `gepa/suites.py`.
- [ ] **Step 4: Run** — expected pass.
- [ ] **Step 5: Commit** `gepa: suites and split`.

### Task 3: Scores and feedback

**Files:**
- Create: `gepa/score.py`
- Test: `gepa/test_score.py`

**Interfaces:**
- Produces:
  - `class InfraError(Exception)`.
  - `is_infra(rec: dict) -> bool` — `rec.get("fake_error")` or `rec["status"] == "error"`.
  - `passed(rec: dict) -> bool` — every gate that is not `None` among `correct`, `quality_gate`, `fake_gate` is true, and `status` ∈ `done`. A record whose gates are all `None` raises `ValueError` (an ungradable task is a suite bug).
  - `task_score(recs: list[dict]) -> float` — fraction of non-infra records passing; raises `InfraError` if all are infra.
  - `feedback(item, recs: list[dict]) -> str` — for the reflection model: the prompt(s), and per failed record: gate names failed (`fake_failed` entries, missing fact **ids**, `forbidden` hit **count**), `status`, the answer (cut at 1500 chars), sub-agent requests (`rec["fake"]["requests"]`, each cut at 300), cost. Never the task's `facts[].match`, `forbidden` patterns or `fake` replies.

- [ ] **Step 1: Write failing tests** `test_passed_ignores_none_gates`, `test_timeout_is_fail_not_infra`, `test_infra_records_excluded`, `test_all_infra_raises`, `test_ungradable_raises`, `test_feedback_has_no_patterns_or_replies` (task with `match: "/out of memory/"` and a scripted reply ⇒ neither string in output; fact id present).
- [ ] **Step 2: Run** `python3 -m pytest gepa/test_score.py -q` — FAIL.
- [ ] **Step 3: Implement** `gepa/score.py`.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `gepa: scores and reflection feedback`.

### Task 4: Guards

**Files:**
- Create: `gepa/guards.py`, `gepa/keep/instruction-leader.txt`, `gepa/keep/turn_reminder-leader.txt`
- Test: `gepa/test_guards.py`

**Interfaces:**
- Consumes: `Item` (Task 2).
- Produces:
  - `denylist(items: list[Item]) -> set[str]` — lower-cased: hostnames/file names/service names from task prompts and scripted replies (tokens containing a digit, `.`, `-` or `_` of length ≥ 4), literal alternatives of fact `match` patterns (split on `|` after stripping `/…/`, words ≥ 5 letters), minus a stoplist of words present in the seed texts (a word already in the seed is not a leak).
  - `leaks(text: str, deny: set[str]) -> list[str]` — whole-word, case-insensitive.
  - `too_long(text: str, seed: str, ratio: float = 1.30) -> bool`.
  - `load_keep(name: str) -> list[str]` — `gepa/keep/<kind>-<target>.txt`, one rule per non-blank, non-`#` line; missing file ⇒ `[]`.
  - `dropped_rules(candidate: dict[str,str], rules: list[str], ask: Callable[[str], str]) -> list[str]` — one call per rule: prompt "Does the text below still state this rule, possibly reworded? Answer YES or NO." with the rule and all candidate components that reach the same agent concatenated; a rule is dropped when the answer does not start with `YES`.
- Seed the two keep files from the leader's instruction and the shipped reminder: the incident-born rules the omnis CLAUDE.md attributes to the leader (sub-agent call is final and an identical re-call repeats it; stop after two unhelpful attempts; independent questions as parallel calls; a single quick lookup stays with the leader; always end with a written answer; state what is unverified). The user reviews these files before the first run (Task 9, Step 1).

- [ ] **Step 1: Write failing tests** `test_denylist_catches_scripted_host`, `test_denylist_skips_seed_words`, `test_leak_whole_word_only`, `test_too_long_ratio`, `test_dropped_rules_uses_whole_candidate` (rule present only in `turn_reminder` ⇒ not dropped), `test_dropped_rule_reported` (stub `ask` returns `NO`).
- [ ] **Step 2: Run** `python3 -m pytest gepa/test_guards.py -q` — FAIL.
- [ ] **Step 3: Implement** `gepa/guards.py`; write the keep files.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `gepa: proposal guards and leader keep lists`.

### Task 5: LLM client, guarded proposer, dollar ceiling

**Files:**
- Create: `gepa/llm.py`, `gepa/proposer.py`, `gepa/ledger.py`
- Test: `gepa/test_proposer.py`, `gepa/test_ledger.py`

**Interfaces:**
- Consumes: guards (Task 4).
- Produces:
  - `llm.Chat(model_id: str, base_url: str, api_key: str, ledger: Ledger | None, prices: tuple[float,float])` — `__call__(prompt: str | list[dict]) -> str` (GEPA `LanguageModel`), OpenAI-compatible `POST {base}/chat/completions` via urllib, temperature 1.0, 2 retries on 5xx, records cost in the ledger. `llm.from_omnis(omnis_src, ref, ledger) -> Chat` reads model id and prices from `config/models.json`.
  - `ledger.Ledger(path: Path)` — `add(usd: float, kind: str)`, `spent() -> float`; append-only JSONL, reloaded on open (resume keeps the total).
  - `ledger.DollarStopper(ledger, ceiling: float)` — GEPA `StopperProtocol`: `__call__(state) -> bool` true once `spent() >= ceiling`.
  - `proposer.GuardedProposer(reflection: Chat, keep_check: Chat, seeds: dict[str,str], deny: set[str], keep: dict[str, list[str]], reach: dict[str, set[str]], log: Path)` — GEPA `ProposalFn`. For each component to update: render `InstructionProposalSignature` with `REFLECTION_TEMPLATE` (GEPA's default template plus three rules: keep every rule of the current text unless the feedback shows it is wrong; never mention task-specific names, hosts, files or expected answers; stay concise), extract the fenced block; reject on: no block / empty / identical to current / `leaks` / `too_long` vs seed / `dropped_rules`; retry up to 2 more times with the rejection reason appended; after 3 rejections return the current text unchanged. Each attempt and verdict is appended to `log` (JSONL).

- [ ] **Step 1: Write failing tests** `test_ledger_resume_keeps_total`, `test_stopper_trips_at_ceiling`, `test_proposer_accepts_clean_text`, `test_proposer_retries_on_leak_then_accepts`, `test_proposer_keeps_parent_after_three_rejections`, `test_proposer_rejects_identical_and_unfenced`, `test_template_has_gepa_placeholders` (`<curr_param>`, `<side_info>`) — with stub `Chat` objects returning canned strings.
- [ ] **Step 2: Run** `python3 -m pytest gepa/test_proposer.py gepa/test_ledger.py -q` — FAIL.
- [ ] **Step 3: Implement** the three modules.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `gepa: guarded proposer, gateway client, dollar ledger`.

### Task 6: Worker (bench servers)

**Files:**
- Create: `gepa/worker.py`
- Test: `gepa/test_worker.py`

**Interfaces:**
- Consumes: `apply_candidate` (Task 1), `fake_agents` (Task 2).
- Produces:
  - `Worker(index: int, workdir: Path, omnis_ref: str, leader_model: str, leaders: list[str], fake: list[str])` — ports: omnis `18900 + 2*index`, fake `18901 + 2*index`.
  - `start() -> None` — starts `fake_subagents.py <fake_port>`, builds the base overlay with `fake_overlay.build_overlay(sys, fake, fake_port, workdir/f"w{index}"/"base", leaders, leader_model)`, runs `MODEL=tiered OVERLAY=<base> setup-ab.sh <workdir> w<index> <omnis_ref> <port>`, waits for `GET /api/squads` (60 s).
  - `apply(candidate: dict[str,str]) -> int` — `apply_candidate(arm_home, base, candidate)`, `POST /api/config/reload`; raises `ReloadError` when the status is not 200, the returned `generation` is not greater than the previous one, or `GET /api/config/parsed/agent` has non-empty `warnings`. Returns the generation.
  - `run(item: Item, repeat: int) -> list[dict]` — subprocess `python3 squad-bench/bench.py --server … --token bench --tasks <file> --task <id> --repeat <r> --nonce --json [--fake <url>]`, timeout `repeat * 600` s, one record per JSON line.
  - `stop() -> None` — `setup-ab.sh <workdir> w<index> stop` and kill the fake server.
  - `restart_model(leader_model: str) -> None` — stop, rebuild base overlay for the model, start (used by the held-out check).

- [ ] **Step 1: Write failing tests** with a stub HTTP server (`http.server` in a thread) standing in for omnis: `test_apply_raises_on_non_200`, `test_apply_raises_when_generation_unchanged`, `test_apply_raises_on_config_warnings`, `test_run_parses_json_lines` (subprocess replaced by a fake script path via a `bench_cmd` constructor argument).
- [ ] **Step 2: Run** `python3 -m pytest gepa/test_worker.py -q` — FAIL.
- [ ] **Step 3: Implement** `gepa/worker.py` (`bench_cmd` defaults to `[sys.executable, "squad-bench/bench.py"]`).
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Live check (one worker, no model cost beyond one task):** start a worker on the omnis `develop` ref with leader model `balanced`, `apply({"turn_reminder:leader": "TEST"})`, confirm via `GET /api/config/parsed/agent` that `leader`'s `turn_reminder` is `TEST` and that a skill overlay `home/registry/skills/<name>/SKILL.md` shadows the shipped one (`GET /api/skills` or the equivalent listing shows the overlay body); run `lf-good` once; `stop()`. Expected: generation increments, one record with `status: done`. If skill shadowing does not hold, stop and report — `skill:` components need another write path.
- [ ] **Step 6: Commit** `gepa: bench worker`.

### Task 7: Adapter

**Files:**
- Create: `gepa/adapter.py`
- Test: `gepa/test_adapter.py`

**Interfaces:**
- Consumes: `Worker` (Task 6), `score` (Task 3), `Ledger` (Task 5).
- Produces: `OmnisAdapter(workers: list[Worker], repeat: int, ledger: Ledger)` implementing GEPA's adapter:
  - `evaluate(batch: list[Item], candidate, capture_traces=False) -> EvaluationBatch` — `apply` the candidate on every worker, distribute items round-robin over workers (one thread per worker, items of a worker run sequentially), add each record's `total_cost_usd` to the ledger; an item whose records are all infra is re-run once; if still infra its score is `0.0` with `trajectory = {"infra": True}` and a warning in the run log (GEPA needs one score per item). `scores` = `task_score`, `objective_scores` = `{"cost": mean total_cost_usd}`, `trajectories` = `{"item": item, "records": recs}` when `capture_traces`.
  - `make_reflective_dataset(candidate, eval_batch, components_to_update) -> dict[str, list[dict]]` — for each component, the items **whose agent the component reaches**, each `{"Inputs": task prompt(s), "Generated Outputs": answer(s), "Feedback": feedback(item, recs)}`; infra items skipped.
- Note: `ReloadError` propagates (GEPA `raise_on_exception=True`); a broken candidate must stop the run, not be scored.

- [ ] **Step 1: Write failing tests** with stub workers: `test_evaluate_scores_in_batch_order`, `test_evaluate_retries_infra_once`, `test_evaluate_infra_twice_scores_zero_and_marks`, `test_reflective_dataset_only_reached_agents`, `test_costs_go_to_ledger`, `test_reload_error_propagates`.
- [ ] **Step 2: Run** `python3 -m pytest gepa/test_adapter.py -q` — FAIL.
- [ ] **Step 3: Implement** `gepa/adapter.py`.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `gepa: omnis adapter`.

### Task 8: Held-out verdict

**Files:**
- Create: `gepa/verdict.py`
- Test: `gepa/test_verdict.py`

**Interfaces:**
- Produces:
  - `suite_mean(recs_by_task: dict[str, list[bool]]) -> float` — mean over tasks of per-task pass fraction.
  - `interval(recs_by_task, level=0.90, n=2000, seed=0) -> tuple[float,float]` — bootstrap resampling repeats **within** each task.
  - `decide(base: dict[tuple[str,str], dict[str,list[bool]]], cand: same) -> dict` → `{"adopt": bool, "rows": [{"agent","model","base_mean","base_lo","base_hi","cand_mean","verdict": "better"|"same"|"worse"}]}`; adopt iff no row `worse` (cand mean < base_lo) and at least one `better` (cand mean > base_hi).

- [ ] **Step 1: Write failing tests** `test_identical_is_same_not_adopted`, `test_one_better_none_worse_adopts`, `test_any_worse_blocks`, `test_interval_deterministic_with_seed`.
- [ ] **Step 2: Run** `python3 -m pytest gepa/test_verdict.py -q` — FAIL.
- [ ] **Step 3: Implement** `gepa/verdict.py`.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `gepa: held-out verdict`.

### Task 9: CLI, run config, report, patch, docs — then the first run

**Files:**
- Create: `gepa/optimize.py`, `gepa/report.py`, `gepa/runs/leader-system.json`, `gepa/README.md`
- Modify: `CLAUDE.md` and `README.md` of omnis-benches (list the tool), `.gitignore` (`gepa/out/`)
- Test: `gepa/test_report.py`, `gepa/test_optimize.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - Run config fields: `name`, `omnis_ref`, `omnis_src` (default `../omnis`), `components` (list), `models` (first = search model), `repeat_search` (2), `repeat_heldout` (5), `workers` (2), `max_metric_calls`, `ceiling_usd` (60), `reflection_ref` (`premium`), `keep_check_ref` (`hosted`), `reflection_minibatch_size` (3), `seed` (0), `heldout_ok_missing` (list).
  - `optimize.py run <config>`: load config → reached agents (union over components) → `suites.load` (refuse with the missing list) → seeds → denylist/keep → workers on `models[0]` → `gepa.optimize(seed_candidate, trainset, valset, adapter, reflection_lm=Chat, custom_candidate_proposer=GuardedProposer, frontier_type="instance", max_metric_calls, stop_callbacks=[DollarStopper], run_dir=gepa/out/<name>, seed)` → held-out: for each model, `restart_model`, evaluate seed and best (repeat 5) on held-out items → `verdict.decide` → `report.write`.
  - `optimize.py calibrate <config>`: one minibatch of `reflection_minibatch_size` train items with the seed on one worker; prints cost per evaluation and the `max_metric_calls` that fits `ceiling_usd` (half of it reserved for held-out).
  - `report.write(out_dir, config, result, verdict, ledger) -> Path` — `reports/gepa-<name>-<YYYY-MM-DD>.md` (config, spend by kind, val score per frontier candidate, the verdict table, best texts and unified diffs vs seed) plus `reports/gepa-<name>-<date>.jsonl` (all records) and `gepa/out/<name>/best.patch` (unified diff against `<omnis_src>` paths: `registry/agents/<a>/instruction.md`, `agent.json` `turn_reminder`, `registry/skills/<s>/SKILL.md`).
  - `gepa/runs/leader-system.json`: components `instruction:leader`, `turn_reminder:leader`; models `balanced`, `premium`; workers 2; ceiling 60.

- [ ] **Step 1: Ask the user to review** `gepa/keep/*.txt` and the leader denylist (`python3 gepa/optimize.py denylist gepa/runs/leader-system.json` prints it). Apply their edits.
- [ ] **Step 2: Write failing tests** `test_refuses_missing_suite` (config with `instruction:knowledge_leader` ⇒ exit with that name), `test_report_contains_verdict_and_diff`, `test_patch_targets_omnis_paths` — no network, stub result objects.
- [ ] **Step 3: Run** `python3 -m pytest gepa -q` — new tests FAIL.
- [ ] **Step 4: Implement** `optimize.py`, `report.py`, the run config, `README.md` (install `pip install -r gepa/requirements.txt`, `.env`, run/calibrate/resume, what the report means, adoption is manual) and the two repo docs.
- [ ] **Step 5: Run** `python3 -m pytest gepa squad-bench -q` — all pass.
- [ ] **Step 6: Commit** `gepa: optimize CLI, report and patch`.
- [ ] **Step 7: Calibrate** `set -a; . ./.env; set +a; python3 gepa/optimize.py calibrate gepa/runs/leader-system.json`; write the printed `max_metric_calls` into the run config; commit.
- [ ] **Step 8: First run** `python3 gepa/optimize.py run gepa/runs/leader-system.json` (background; resumable with the same command). Expected: a report under `reports/`, total spend ≤ $60 per the ledger.
- [ ] **Step 9: Commit** the report and records; tell the user the verdict and where the patch is. Do not apply the patch to omnis.
