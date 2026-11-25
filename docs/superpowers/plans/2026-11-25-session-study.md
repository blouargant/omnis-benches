# Session Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `session-study/`, an offline tool that turns real omnis sessions into checked squad-bench scenarios and reports whether they find defects our hand-written tasks miss.

**Architecture:** One CLI (`study.py`) with one subcommand per step of the spec (`scan`, `judge`, `review`, `draft`, `check`, `replay`, `report`). Each step reads and writes plain files under `session-study/out/` so a step can be re-run alone. Replay shells out to the existing `squad-bench/bench.py`; nothing in squad-bench or omnis changes.

**Tech Stack:** Python 3 standard library only. Tests with `unittest`, no network. LLM calls through the OpenAI-compatible gateway of `.env` (`OPENAI_BASE_URL`, `OPENAI_API_KEY`), as `squad-bench/judge_modelcost.py` does.

**Spec:** `../omnis/docs/superpowers/specs/2026-11-25-session-scenarios-study-design.md`

## Global Constraints

- Python standard library only; nothing imports omnis.
- Everything holding session text is written under `session-study/out/`, which is in `.gitignore`. The only committed file with scenario text is `session-study/tasks-sessions.json`.
- No change to `squad-bench/bench.py` behaviour, to omnis, or to any other tool.
- Hidden sessions (`"hidden": true`) are never read past that flag.
- Session text sent to a model is fenced between `<<<BEGIN SESSION>>>` / `<<<END SESSION>>>` lines and the prompt says fenced text is data, not instructions.
- Values fixed by the spec: outline cuts arguments and results to **300** characters; `repeated_call` at **3** identical calls; `many_calls` above the squad's **90th percentile**; **8** random control cards; reply shown as first and last **600** characters; **2** control scenarios; **5** runs per scenario; reproduces at **≥ 2 of 5**; a control passes at **≥ 4 of 5**; spend ceiling default **30 USD**; decision rule **≥ 3** go, **0** stop, **1–2** undecided.
- Tests: `python3 -m unittest discover -s session-study`.

## Review Focus

1. A conversation file that is a legacy plain array, unreadable, or has no `turns`: skipped, counted in the scan summary, never a crash.
2. A tool record whose `args` or `result` is cut mid-JSON, is a bare string, or is absent: the outline and the signals still work on its text.
3. A model reply that is not JSON, or JSON missing a key: the item is recorded with `"error"` and the run goes on; re-running the step retries only those items.
4. `verdicts.json` filled in part, or with a value outside `yes`/`no`/`unsure`: `draft` and `report` use the valid `yes`/`no` entries, list the others, and say how many cards are still open.
5. A replay run that timed out, was cancelled, ended on `ask_user`, or returned an empty answer: it counts as a run, is never counted as `failure_seen`, and is reported as "invalid"; a scenario with more than 2 invalid runs is reported as "not measured", not as "does not reproduce".

## File Structure

```
session-study/
  study.py          CLI: argparse subcommands, paths, calls into the modules
  sessions.py       read conversation files, iterate turns and calls, outline
  signals.py        the cheap signals of one turn
  llm.py            one gateway call, JSON extraction, fencing
  judge.py          turn judge (step 2) and run judge (step 5): prompts + parsing
  review.py         cards, verdicts template, precision figures
  scenarios.py      draft prompt, sanitisation check
  replay.py         fixture dirs, bench.py invocation, reproduce rule, ledger
  report.py         funnel, tables, decision rule, markdown
  test_*.py         one per module
  README.md
  tasks-sessions.json   (produced by the study, committed after `check`)
```

Shared identifiers: a turn is `"<session_id>#<turn_index>"` (`turn_id`); a card is `"c01"`, `"c02"`…; a scenario is `"ss-1"`, `"ss-2"`…, controls `"ss-c1"`, `"ss-c2"`.

Files under `out/`: `turns.jsonl`, `judged.jsonl`, `cards.json`, `review.md`, `verdicts.json`, `scenarios-draft.json`, `sources.json`, `fixtures/`, `tasks-replay.json`, `runs.jsonl`, `run-judged.jsonl`, `ledger.jsonl`, `coverage.json`.

---

### Task 1: Read sessions and compute signals (`scan`)

**Files:**
- Create: `session-study/sessions.py`, `session-study/signals.py`, `session-study/study.py`
- Test: `session-study/test_sessions.py`, `session-study/test_signals.py`
- Modify: `.gitignore` (add `session-study/out/`)

**Interfaces:**
- Produces:
  - `sessions.load(logs_dir: str) -> tuple[list[dict], dict]` — sessions as `{"id", "squad", "skills": [{"name","turn"}], "turns": [...]}`, and a summary `{"files", "hidden", "legacy", "unreadable"}`. The id is the file name without `conversation_` and `.json`.
  - `sessions.walk(calls: list) -> Iterator[tuple[dict, int]]` — each call with its depth, children included.
  - `sessions.text_of(raw) -> str` — the text of an `args`/`result` value whatever its shape (dict, list, string, cut JSON, None).
  - `sessions.outline(turn: dict, cut: int = 300) -> str` — one line per call `"<indent><agent>.<name>(<args>) -> <result>"`, both cut to `cut` characters, children indented by two spaces.
  - `signals.for_turn(turn: dict, next_user_text: str, p90_calls: float) -> list[str]` — names from the spec's table.
  - `signals.p90(counts: list[int]) -> float`
  - `study.py scan [--logs DIR] [--out DIR]` writes `out/turns.jsonl`, one object per turn that has tool calls: `{"turn_id","session","turn","squad","skills","calls","calls_by_agent","tokens","signals","user_text","reply","next_user_text","outline"}`.

- [ ] **Step 1: Write the failing tests**

`test_sessions.py`, on files written to a temp dir:

```python
def test_load_skips_hidden_legacy_and_unreadable(self):
    # one good file, one {"hidden": true}, one plain array, one "{not json"
    sess, summary = sessions.load(self.dir)
    self.assertEqual([s["id"] for s in sess], ["good"])
    self.assertEqual(summary, {"files": 4, "hidden": 1, "legacy": 1, "unreadable": 1})

def test_text_of_survives_any_shape(self):
    self.assertEqual(sessions.text_of(None), "")
    self.assertEqual(sessions.text_of("plain"), "plain")
    self.assertIn("Error: boom", sessions.text_of({"output": "Error: boom"}))
    self.assertIn("cut", sessions.text_of('{"output": "cut'))

def test_outline_nests_children_and_cuts(self):
    turn = {"tools": [{"name": "web_agent", "args": {"request": "x" * 400},
                       "children": [{"name": "WebFetch", "agent": "web_agent",
                                     "args": {"url": "https://e.x"}, "result": {"output": "ok"}}]}]}
    lines = sessions.outline(turn).splitlines()
    self.assertEqual(len(lines), 2)
    self.assertTrue(lines[1].startswith("  web_agent.WebFetch("))
    self.assertLessEqual(len(lines[0]), 700)
```

`test_signals.py`, one test per row of the spec's table, each asserting the signal is present on a turn built for it and absent on a clean turn. Exact triggers:

```python
def test_tool_error(self):        # result {"output": "Error: no such file"} and {"error": "x"}
def test_blocked(self):           # "[BLOCKED BY HOOK] ...", "[BLOCKED BY AUTO MODE] ...", "Permission denied by user"
def test_halted(self):            # result containing "Do NOT call any more tools"
def test_empty_subagent(self):    # "stopped without writing a result"
def test_repeated_call(self):     # same name+args 3 times -> yes; 2 times -> no; children counted
def test_many_calls(self):        # 11 calls with p90_calls=10 -> yes; 10 -> no
def test_reply_cut_and_empty(self):  # reply containing "[Reply cut" ; reply ""
def test_user_pushback(self):     # next text "Non, ce n'est pas ça" / "No, that's wrong" -> yes; "Merci" / "" -> no
def test_clean_turn_has_no_signal(self):
```

Before writing `test_blocked` and `test_halted`, read the exact notice texts in the omnis checkout (`core/permissions` `DeniedPrefix` and `AutoBlockPrefix`, `agent/budget_plugin.go` `budgetHaltNotice`, `agentCapNotice`, the per-call cap notice in `agent/call_cap.go`, `agent/hooks_plugin.go` for the hook block) and use those strings in the fixtures and in the rule.

- [ ] **Step 2: Run them, expect failure**

Run: `python3 -m unittest discover -s session-study`
Expected: import errors.

- [ ] **Step 3: Implement `sessions.py`, `signals.py` and the `scan` subcommand**

The pushback word list (matched at the start of the next user message, case-insensitive): `non`, `no`, `pas `, `ce n'est pas`, `c'est faux`, `faux`, `tu te trompes`, `wrong`, `incorrect`, `that's not`, `toujours pas`, `ça ne marche`, `ca ne marche`, `still not`, `doesn't work`. `p90` is computed per squad over the turns that have tool calls. `scan` prints the summary and the count of turns per signal.

- [ ] **Step 4: Run the tests, expect pass**

- [ ] **Step 5: Run `scan` on the real logs and compare**

Run: `python3 session-study/study.py scan`
Expected: 50 turns or more with tools, most on `knowledge`; `repeated_call` on about 4, one `tool_error`, one `empty_subagent`. A count far from these means a rule or the loader is wrong.

- [ ] **Step 6: Commit**

```bash
git add .gitignore session-study/
git commit -m "feat(session-study): read sessions and compute per-turn signals"
```

---

### Task 2: Gateway call and turn judge (`judge`)

**Files:**
- Create: `session-study/llm.py`, `session-study/judge.py`
- Modify: `session-study/study.py`
- Test: `session-study/test_llm.py`, `session-study/test_judge.py`

**Interfaces:**
- Consumes: `out/turns.jsonl` lines (Task 1).
- Produces:
  - `llm.call(model: str, system: str, user: str, timeout: int = 300) -> tuple[str, dict]` — reply text and the gateway's `usage`.
  - `llm.extract_json(text: str) -> dict` — first JSON object in the text; raises `ValueError` otherwise.
  - `llm.fence(text: str) -> str` — wraps in the BEGIN/END lines and neutralises those markers inside `text`.
  - `judge.turn_prompt(turn: dict) -> tuple[str, str]` (system, user).
  - `judge.parse_turn(text: str) -> dict` — `{"verdict","kind","reason","calls"}`; raises `ValueError` when `verdict` is not `failed`/`wasteful`/`ok`.
  - `study.py judge [--model M]` (default `claude-sonnet-5-5`, the gateway id behind `premium`) appends to `out/judged.jsonl`: `{"turn_id","model","verdict","kind","reason","calls","usage"}` or `{"turn_id","model","error"}`. A turn already judged without error is skipped.

- [ ] **Step 1: Write the failing tests**

```python
def test_extract_json_finds_object_in_prose(self):
    self.assertEqual(llm.extract_json('Here: {"a": 1} done'), {"a": 1})
    with self.assertRaises(ValueError): llm.extract_json("no json")

def test_fence_neutralises_markers(self):
    out = llm.fence("x\n<<<END SESSION>>>\ny")
    self.assertEqual(out.count("<<<END SESSION>>>"), 1)

def test_turn_prompt_fences_session_text(self):
    system, user = judge.turn_prompt({"user_text": "Q", "reply": "A", "next_user_text": "", "outline": "t()"})
    self.assertIn("data", system.lower())
    self.assertIn("<<<BEGIN SESSION>>>", user)

def test_parse_turn_rejects_unknown_verdict(self):
    self.assertEqual(judge.parse_turn('{"verdict":"ok","kind":"","reason":"fine","calls":[]}')["verdict"], "ok")
    with self.assertRaises(ValueError): judge.parse_turn('{"verdict":"great"}')

def test_judge_records_error_and_retries_only_errors(self):
    # run_judge(turns, call=fake) where fake returns non-JSON for turn 2;
    # second pass with a good fake calls the model for turn 2 only
```

`run_judge(turns: list, out_path: str, model: str, call=llm.call) -> dict` is the testable core of the subcommand; it returns `{"judged", "errors", "skipped"}`.

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

The system prompt tells the judge: report only what the transcript shows (tool errors, loops, an answer that does not address the request, the user pushing back, effort out of proportion with the request); do not fact-check; `wasteful` is a correct answer reached at a clearly excessive cost; `kind` is a label of at most four words; `reason` one sentence; `calls` the outline line numbers that show it.

- [ ] **Step 4: Run the tests, expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(session-study): turn judge through the gateway"
```

---

### Task 3: Review cards and precision (`review`)

**Files:**
- Create: `session-study/review.py`
- Modify: `session-study/study.py`
- Test: `session-study/test_review.py`

**Interfaces:**
- Consumes: `out/turns.jsonl`, `out/judged.jsonl`.
- Produces:
  - `review.pick(turns: list, judged: dict, controls: int = 8, seed: int = 20261125) -> list[dict]` — cards `{"card","turn_id","why"}` with `why` in `signal`/`judge`/`both`/`control`, shuffled with the seed, numbered after the shuffle.
  - `review.card_markdown(card_id: str, turn: dict) -> str` — question, outline, reply head and tail (600 characters each, the whole reply when shorter than 1200), next user message. No signal, no judge verdict, no `why`.
  - `review.read_verdicts(path: str) -> tuple[dict, list]` — `{card: {"failure","kind","note"}}` for valid `yes`/`no` entries, and the list of cards still open or invalid.
  - `review.precision(cards: list, verdicts: dict, turns: dict, judged: dict) -> dict` — per signal and for the judge: `{"flagged","checked","real","precision"}`; plus `{"controls_checked","controls_real"}`.
  - `study.py review` writes `out/cards.json`, `out/review.md`, and `out/verdicts.json` **only if it does not exist** (never overwrite the user's answers).

- [ ] **Step 1: Write the failing tests**

```python
def test_pick_takes_every_candidate_and_eight_controls(self):
    # 20 turns: 3 with a signal, 2 judged "failed" (one overlaps) -> 4 candidates + 8 controls
    cards = review.pick(turns, judged)
    self.assertEqual(len(cards), 12)
    self.assertEqual(sum(c["why"] == "control" for c in cards), 8)

def test_pick_with_fewer_clean_turns_than_controls(self):  # 3 clean turns -> 3 controls, no error

def test_card_hides_signals_and_verdict(self):
    md = review.card_markdown("c01", turn_with_signals)
    for word in ("repeated_call", "wasteful", "control", "signal"): self.assertNotIn(word, md)

def test_long_reply_shows_head_and_tail(self):  # 5000-char reply -> both ends present, middle absent

def test_read_verdicts_separates_open_and_invalid(self):
    # {"c01":{"failure":"yes"}, "c02":{"failure":""}, "c03":{"failure":"maybe"}, "c04":{"failure":"unsure"}}
    valid, open_ = review.read_verdicts(path)
    self.assertEqual(set(valid), {"c01"}); self.assertEqual(set(open_), {"c02", "c03", "c04"})

def test_review_does_not_overwrite_verdicts(self):

def test_precision_counts(self):
    # signal X flagged 4, 3 checked, 2 real -> precision 2/3
```

`unsure` is a valid answer for the user but is not a `yes`/`no`: it is listed with the open cards and counted apart in the report.

- [ ] **Step 2: Run, expect failure**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the tests, expect pass**
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(session-study): review cards, verdict file, precision"
```

---

### Task 4: Draft scenarios and check them (`draft`, `check`)

**Files:**
- Create: `session-study/scenarios.py`
- Modify: `session-study/study.py`
- Test: `session-study/test_scenarios.py`

**Interfaces:**
- Consumes: `out/cards.json`, `out/verdicts.json`, `out/turns.jsonl`; `llm.call`, `llm.extract_json`, `llm.fence`.
- Produces:
  - `scenarios.draft_prompt(turn: dict, earlier_user_texts: list[str], failure_kind: str, note: str, control: bool) -> tuple[str, str]`
  - `scenarios.parse_draft(text: str, scenario_id: str, squad: str) -> dict` — the spec's shape with `prompt` (one request) or `prompts` (several), `kind`, `rubric: {"pass": [...], "failure": str}`, optional `files`; raises `ValueError` when the request or `rubric.pass` is empty, or a control has a non-empty `rubric.failure`.
  - `scenarios.leaks(source_text: str, draft: dict) -> list[str]` — tokens of the source still present in the draft.
  - `study.py draft [--model M]` writes `out/scenarios-draft.json` (list) and `out/sources.json` (`{scenario_id: turn_id}`); scenarios for every card marked `yes`, then 2 controls from cards marked `no`, same squad as the failures when possible.
  - `study.py check` prints the leaks per draft and exits 1 when there is one; `study.py check --accept ss-1,ss-3,ss-c1` copies those drafts, if clean, to `session-study/tasks-sessions.json`.

- [ ] **Step 1: Write the failing tests**

```python
def test_leaks_finds_names_paths_hosts_numbers(self):
    src = "Compare Acme Corp's cluster at gw.acme.example, see /home/bob/notes.md, budget 48000"
    draft = {"prompt": "Compare Acme's cluster, budget 48000", "rubric": {"pass": ["x"], "failure": ""}}
    self.assertEqual(sorted(scenarios.leaks(src, draft)), ["48000", "Acme"])

def test_leaks_ignores_sentence_starts_and_common_tech_words(self):
    # "Compare", "Kubernetes", "Python", "GPU" in both -> not leaks

def test_leaks_looks_into_files_and_rubric(self):

def test_parse_draft_requires_request_and_pass_criteria(self):
def test_control_must_have_empty_failure(self):
def test_accept_refuses_a_leaking_draft(self):
def test_draft_skips_open_and_unsure_cards(self):
```

A leak token is: a capitalised word that is not the first word of a sentence, a path (contains `/` and a letter), a host name (`a.b` with a letter-only last label), an e-mail address, or a number of 4 digits or more. A fixed allow-list of product and technology names lives in `scenarios.py` (`ALLOWED`); the check output says which tokens were allowed so the reader can still spot a wrong one.

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

The draft prompt asks for: the same task with every name, path, host and figure replaced by an invented one of the same kind; `rubric.pass` as 2 to 5 checkable statements; `rubric.failure` as one sentence naming the specific failure of the session (from the user's `kind` and `note`), observable in an answer or in run metrics; `files` only when the turn read local files.

- [ ] **Step 4: Run the tests, expect pass**
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(session-study): scenario drafts and sanitisation check"
```

---

### Task 5: Replay and judge the runs (`replay`)

**Files:**
- Create: `session-study/replay.py`
- Modify: `session-study/judge.py`, `session-study/study.py`
- Test: `session-study/test_replay.py`, additions to `session-study/test_judge.py`

**Interfaces:**
- Consumes: `session-study/tasks-sessions.json`; `squad-bench/bench.py` as a subprocess; its record fields `task`, `status`, `answer`, `answers`, `total_cost_usd`, `delegations`, `leader_tools`, `subagent_tools`, `fetches`, `wall_ms`.
- Produces:
  - `replay.materialise(scenarios: list, out_dir: str) -> str` — writes each scenario's `files` under `out/fixtures/<id>/`, and `out/tasks-replay.json` in squad-bench's format (`id`, `squad`, `prompt` or `prompts`, `kind`, `cwd` set to the fixture dir when there are files); returns its path. `rubric` and `files` are not copied into it.
  - `replay.spent(ledger_path: str) -> float`
  - `replay.valid(record: dict) -> bool` — false when `status` is `timeout`, `cancelled`, `ask_user` or `error`, or the answer is empty.
  - `judge.run_prompt(scenario: dict, record: dict) -> tuple[str, str]` and `judge.parse_run(text: str) -> dict` — `{"passed": bool, "failure_seen": bool, "reason": str}`.
  - `replay.outcome(scenario: dict, judged_runs: list[dict]) -> dict` — `{"runs","invalid","passed","failure_seen","status"}` with `status` in `reproduces` / `does_not_reproduce` / `not_measured` for a failure scenario, `control_ok` / `control_fails` / `not_measured` for a control.
  - `study.py replay --server URL [--token T] [--repeat 5] [--ceiling 30] [--deadline 900] [--judge-model gpt-5.5]` appends bench records to `out/runs.jsonl`, one cost line per run to `out/ledger.jsonl`, and judged runs to `out/run-judged.jsonl`.

- [ ] **Step 1: Write the failing tests**

```python
def test_materialise_writes_files_and_strips_rubric(self):
    path = replay.materialise([{"id": "ss-1", "squad": "knowledge", "prompt": "Q",
                                "rubric": {"pass": ["a"], "failure": "f"}, "files": {"a.txt": "hi"}}], self.out)
    task = json.load(open(path))[0]
    self.assertNotIn("rubric", task); self.assertNotIn("files", task)
    self.assertEqual(open(os.path.join(task["cwd"], "a.txt")).read(), "hi")

def test_materialise_refuses_a_file_name_that_leaves_the_fixture_dir(self):  # "../x", "/etc/x"

def test_valid_rejects_timeout_ask_user_and_empty_answer(self):

def test_outcome_reproduces_at_two_of_five(self):
    # failure_seen on 2 valid runs of 5 -> "reproduces"; on 1 -> "does_not_reproduce"
def test_outcome_not_measured_with_three_invalid_runs(self):
def test_invalid_run_never_counts_as_failure_seen(self):
def test_control_ok_at_four_of_five(self):

def test_replay_stops_at_ceiling(self):
    # run_replay(scenarios, repeat=5, ceiling=1.0, run=fake costing 0.4) -> 3 runs, summary["stopped"] == "ceiling"

def test_replay_resumes(self):
    # runs.jsonl already has 3 runs of ss-1 -> only 2 more are started
```

`run_replay(scenarios, out_dir, repeat, ceiling, run, judge_run) -> dict` is the testable core; `run(task_id) -> dict` wraps the `bench.py` subprocess and `judge_run(scenario, record) -> dict` wraps the model call. The ceiling is checked before each run against `replay.spent`.

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

`bench.py` is called once per run: `python3 squad-bench/bench.py --server … --token … --tasks out/tasks-replay.json --task <id> --nonce --deadline <d> --json`, and the record is read from its standard output. Check `bench.py`'s record against the field list above before relying on it. The run judge receives the scenario's request, its rubric, the run's answer and a metrics line (tool calls, delegations, fetches, cost, seconds); it is told that `failure_seen` means the rubric's specific failure, not any shortcoming, and that an invalid run was already set aside.

- [ ] **Step 4: Run the tests, expect pass**
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(session-study): replay scenarios and judge the runs"
```

---

### Task 6: Report and documentation (`report`)

**Files:**
- Create: `session-study/report.py`, `session-study/README.md`
- Modify: `session-study/study.py`, `CLAUDE.md` (a `session-study/` entry beside the other tools, with the test command), `README.md` (one line in the tool list)
- Test: `session-study/test_report.py`

**Interfaces:**
- Consumes: every file of `out/`; `out/coverage.json`, written by hand as `{"ss-1": {"covered_by": "", "group": "<label>"}}` (`covered_by` names an existing tasks file, empty when none; scenarios sharing a `group` are one failure).
- Produces:
  - `report.decide(outcomes: dict, coverage: dict) -> tuple[str, int]` — `("go"|"stop"|"undecided", n)` where `n` is the number of distinct groups that reproduce and have an empty `covered_by`.
  - `report.build(out_dir: str, tasks_path: str) -> str` — the markdown.
  - `study.py report [--date YYYY-MM-DD]` writes `reports/session-scenarios-knowledge-<date>.md`.

- [ ] **Step 1: Write the failing tests**

```python
def test_decide(self):
    # 3 reproducing, uncovered, distinct groups -> ("go", 3)
    # 3 reproducing but two share a group -> ("undecided", 2)
    # 2 reproducing, one covered_by "tasks-web.json" -> ("undecided", 1)
    # none reproducing -> ("stop", 0)
    # a reproducing scenario absent from coverage.json -> ValueError naming it

def test_report_has_funnel_and_no_session_text(self):
    # build on a fixture out/ whose turns contain the marker "SECRET-SESSION-TEXT"
    md = report.build(self.out, self.tasks)
    self.assertNotIn("SECRET-SESSION-TEXT", md)
    for label in ("Turns scanned", "Flagged", "Confirmed failures", "Scenarios", "Reproduce", "Not covered"):
        self.assertIn(label, md)

def test_report_lists_open_cards_and_not_measured_scenarios(self):
def test_report_flags_failing_controls(self):   # a control_fails line and a warning above the verdict
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

Sections, in this order: scope (machine count, dates of the first and last recorded turn, turns per squad); funnel; precision table (one row per signal, one for the judge, one for the random controls); scenarios table (id, failure sentence, runs, `failure_seen`, status, cost); coverage (per reproducing scenario: group, covered by); missing signals (a fixed list — Stop, rewind, tool records of injected turns, file state — plus any `note` of a verdict that names one); spend; verdict with the rule quoted; limits copied from the spec. Scenario text comes from `tasks-sessions.json` only.

The README says what the tool is for, the seven commands in order, what the user fills in (`verdicts.json`, `coverage.json`), and that `out/` holds session text and is never committed.

- [ ] **Step 4: Run the tests, expect pass**

Run: `python3 -m unittest discover -s session-study`

- [ ] **Step 5: Commit**

```bash
git add -A session-study CLAUDE.md README.md
git commit -m "feat(session-study): report, decision rule, docs"
```

---

### Task 7: Run the study

Not code. Each step ends on something to show the user.

- [ ] **Step 1:** `set -a; . ./.env; set +a`, then `study.py scan` and `study.py judge`. Show the signal counts and the judge's verdict counts.
- [ ] **Step 2:** `study.py review`. Hand `out/review.md` and `out/verdicts.json` to the user. **Wait** for the verdicts.
- [ ] **Step 3:** `study.py draft`, then `study.py check`. Read every draft; fix or drop the ones that leak or that do not state a checkable failure. Show the drafts to the user and get the list to accept; `study.py check --accept …`.
- [ ] **Step 4:** Start a production-tier server: `MODEL=tiered squad-bench/setup-ab.sh <workdir> study worktree <port>` (see that script's header), then `study.py replay --server http://127.0.0.1:<port> --token bench`. Stop the server afterwards.
- [ ] **Step 5:** Write `out/coverage.json` by reading the existing tasks files (`squad-bench/tasks-*.json`); state the reasoning for each line to the user.
- [ ] **Step 6:** `study.py report`. Commit `session-study/tasks-sessions.json` and the report. Tell the user the verdict and the three numbers behind it.
