# Fake sub-agents for squad-bench — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let squad-bench run a squad whose sub-agents answer from a per-task script, so the leader's delegation behaviour can be measured alone.

**Architecture:** A local OpenAI-compatible server (`fake_subagents.py`) answers for the faked agents; a config overlay points their `model_ref` at it; `bench.py --fake URL` posts each task's script before the run and reads the call log after; `scoring.py` turns the log into numbers and a pass/fail gate.

**Tech Stack:** Python 3 stdlib only (`http.server`, `urllib`, `unittest`). No omnis change.

**Spec:** `docs/superpowers/specs/2026-11-22-fake-subagents-design.md`

## Global Constraints

- Everything lives in `omnis-benches/squad-bench`; nothing imports omnis; stdlib only.
- Tests are `unittest`, run with `python3 -m unittest discover -s squad-bench`.
- Faked agent model id: `fake-<agent>`. Provider name: `fake`.
- Unscripted call, or agent absent from the script: reply exactly `No evidence found.`
- Default `delay_ms`: 300.
- Request text cut at 500 chars in the bench record.
- The fake never returns a tool call.
- A task with a `fake` block and no `--fake` is an error before any task runs.
- Commit messages end with `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.

## Review Focus

1. `POST /scenario` with a malformed script (not a dict of lists, a rule with neither `reply` nor `status`) → HTTP 400 with a message, previous scenario kept. Test in Task 2.
2. A chat request whose user `content` is a list of parts, or with several user messages → the request text is the text of the **last** user message. Test in Task 1.
3. Several calls arriving at once → every call logged once, `times` never over-spent. Test in Task 2.
4. `--fake` given but the server is down → bench exits with a message naming the URL, before creating a session. Test in Task 5.
5. A model id without the `fake-` prefix → the agent name is the id as is; no crash. Test in Task 1.

Known and accepted, not tested: omnis retries an HTTP 5xx, so a `status` rule is logged once per attempt. The shipped scenarios do not use `status`.

---

## File Structure

| File | Responsibility |
|---|---|
| `squad-bench/fake_subagents.py` | Script engine (pure) + HTTP server |
| `squad-bench/test_fake_subagents.py` | Engine and server tests |
| `squad-bench/scoring.py` (modify) | `fake_summary`, `check_fake` |
| `squad-bench/fake_overlay.py` | Config overlay |
| `squad-bench/test_fake_overlay.py` | Overlay tests |
| `squad-bench/bench.py` (modify) | `--fake`, scenario begin/end, record fields |
| `squad-bench/tasks-leader-fake.json` | The four scenarios |
| `squad-bench/README-leader-fake.md` | How to run |

---

### Task 1: Script engine

**Files:**
- Create: `squad-bench/fake_subagents.py`, `squad-bench/test_fake_subagents.py`

**Interfaces — Produces:**
- `DEFAULT_REPLY = "No evidence found."`
- `agent_of(model: str) -> str` — strips a leading `fake-`.
- `request_text(messages: list) -> str` — text of the last `role == "user"` message; `content` may be a string or a list of `{"text": ...}` parts; `""` when none.
- `normalise(text: str) -> str` — `" ".join(text.lower().split())`.
- `validate_script(script) -> str | None` — error message, or `None` when valid. Valid: a dict mapping agent name to a list of dicts, each with `reply` (str) or `status` (int).
- `class Scenario(task: str, script: dict)` with
  `answer(agent: str, request: str) -> dict` returning
  `{"reply": str | None, "status": int | None, "delay_ms": int, "rule": int | None}` and recording the request in the agent's history. Thread-safe (one lock).
  Rule selection: first rule, in order, that is usable — `when` absent or `scoring.match_rule(when, request)`; uses so far `< times` when `times` is set; and, with `if_new_request`, `normalise(request)` differs from every earlier request of that agent. No usable rule → `DEFAULT_REPLY`, `rule: None`, `delay_ms: 300`.

- [x] **Step 1: Write the failing tests** (`class TestEngine`)

```python
RULES = {"investigator": [
    {"times": 1, "reply": "off-topic", "delay_ms": 0},
    {"if_new_request": True, "reply": "good", "delay_ms": 0},
    {"reply": "off-topic again", "delay_ms": 0}]}

def test_reworded_request_gets_the_good_reply(self):
    s = fs.Scenario("t", RULES)
    self.assertEqual(s.answer("investigator", "why did it fail")["reply"], "off-topic")
    self.assertEqual(s.answer("investigator", "Why  did it FAIL")["reply"], "off-topic again")
    self.assertEqual(s.answer("investigator", "check the kernel log")["reply"], "good")

def test_when_selects_by_request(self):
    s = fs.Scenario("t", {"investigator": [
        {"when": "/reports/", "reply": "B"}, {"when": "orders-sync", "reply": "A"}]})
    self.assertEqual(s.answer("investigator", "check orders-sync")["reply"], "A")
    self.assertEqual(s.answer("investigator", "who filled /var/spool/reports")["reply"], "B")

def test_unscripted_call_gets_the_default(self):
    s = fs.Scenario("t", {})
    a = s.answer("helper", "anything")
    self.assertEqual((a["reply"], a["rule"], a["delay_ms"]), ("No evidence found.", None, 300))

def test_status_rule(self):
    a = fs.Scenario("t", {"x": [{"status": 500}]}).answer("x", "q")
    self.assertEqual((a["status"], a["reply"]), (500, None))

def test_request_text_takes_the_last_user_message(self):
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "first"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": [{"type": "text", "text": "second "}, {"type": "text", "text": "part"}]}]
    self.assertEqual(fs.request_text(msgs), "second part")
    self.assertEqual(fs.request_text([]), "")

def test_agent_of(self):
    self.assertEqual(fs.agent_of("fake-investigator"), "investigator")
    self.assertEqual(fs.agent_of("gpt-x"), "gpt-x")

def test_validate_script(self):
    self.assertIsNone(fs.validate_script(RULES))
    self.assertIsNotNone(fs.validate_script([]))
    self.assertIsNotNone(fs.validate_script({"a": [{"delay_ms": 1}]}))
```

- [x] **Step 2: Run** `python3 -m unittest squad-bench/test_fake_subagents.py` — expect an import error.
- [x] **Step 3: Implement** the functions and `Scenario` above (import `scoring` for `match_rule`).
- [x] **Step 4: Run** the same command — expect all tests to pass.
- [x] **Step 5: Commit** `feat(squad-bench): script engine for fake sub-agents`.

---

### Task 2: HTTP server

**Files:**
- Modify: `squad-bench/fake_subagents.py`, `squad-bench/test_fake_subagents.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `serve(port: int) -> ThreadingHTTPServer` — binds `127.0.0.1`; port 0 picks a free port; state (current `Scenario`, call log, lock) lives on the server object. `main()` runs `serve(int(sys.argv[1])).serve_forever()`.
  - `POST /scenario` body `{"task": str, "script": dict}` → 200 `{"ok": true}`; invalid → 400 `{"error": msg}`, state unchanged. Clears the log.
  - `GET /calls` → `{"task": str, "calls": [{"agent", "n", "request", "rule", "started_ms", "ended_ms"}]}`; `n` is 1-based per agent; times are ms since the scenario was set.
  - `GET /v1/models` → `{"data": []}`.
  - `POST /v1/chat/completions` (any path ending in `/chat/completions`): sleeps `delay_ms`, then answers with the reply as assistant text, `finish_reason: "stop"`, usage `{prompt_tokens: 1, completion_tokens: 1, total_tokens: 2}`; streaming when `stream` is true, in the same chunk shape as `prompt-size/fake_server.py`. A `status` rule answers that HTTP status with `{"error": {"message": "scripted failure"}}`. With no scenario set, behaves as an empty script.

- [x] **Step 1: Write the failing tests** (`class TestServer`, server on port 0 in a thread, `urllib` client)

```python
def test_chat_reply_and_log(self):
    post("/scenario", {"task": "t", "script": {"investigator": [{"reply": "found", "delay_ms": 0}]}})
    r = post("/v1/chat/completions", {"model": "fake-investigator",
        "messages": [{"role": "user", "content": "why"}]})
    self.assertEqual(r["choices"][0]["message"]["content"], "found")
    calls = get("/calls")["calls"]
    self.assertEqual([(c["agent"], c["n"], c["request"], c["rule"]) for c in calls],
                     [("investigator", 1, "why", 0)])

def test_streaming_reply(self):          # body contains "found" and ends with "data: [DONE]"
def test_bad_scenario_is_refused_and_keeps_the_previous_one(self):   # 400, then a chat still gets "found"
def test_scenario_clears_the_log(self):
def test_status_rule_returns_that_status(self):                      # urllib HTTPError code 503
def test_parallel_calls_are_all_logged_and_times_is_respected(self):
    # script: [{"times": 2, "reply": "limited", "delay_ms": 50}], 8 threads
    # -> 8 calls logged, exactly 2 replies "limited", 6 "No evidence found."
def test_overlapping_calls_overlap_in_the_log(self):
    # 2 threads, delay_ms 200 -> calls[0].ended_ms > calls[1].started_ms
```

- [x] **Step 2: Run** — expect failures (`serve` undefined).
- [x] **Step 3: Implement** `serve`, the handler and `main`.
- [x] **Step 4: Run** `python3 -m unittest squad-bench/test_fake_subagents.py` — all pass.
- [x] **Step 5: Commit** `feat(squad-bench): fake sub-agent model server`.

---

### Task 3: Scoring

**Files:**
- Modify: `squad-bench/scoring.py`, `squad-bench/test_bench.py` (add `class TestFakeScoring`)

**Interfaces — Produces:**
- `fake_summary(calls: list) -> dict` returning
  `{"calls": {agent: n}, "distinct_requests": {agent: n}, "repeats": {agent: n}, "max_parallel": int, "requests": [{"agent", "n", "request"}]}`.
  Distinct is counted on whitespace- and case-normalised text; `repeats = calls - distinct`; `max_parallel` is the largest number of `[started_ms, ended_ms)` intervals open at once, all agents together; `request` cut at 500 chars. Empty list → all empty, `max_parallel` 0.
- `check_fake(expect: dict | None, summary: dict) -> dict` returning `{"fake_gate": bool | None, "fake_failed": [str]}`. `expect` shape: `{"agents": {agent: {"min_calls", "max_calls", "min_distinct", "max_repeats"}}, "min_parallel": int}`, every key optional. A missing agent counts as 0. Failed ids: `"<agent>.<key>"` and `"min_parallel"`. `expect` falsy → `fake_gate: None`.

- [x] **Step 1: Write the failing tests**

```python
CALLS = [
    {"agent": "investigator", "n": 1, "request": "Why did it fail", "rule": 0, "started_ms": 0, "ended_ms": 300},
    {"agent": "investigator", "n": 2, "request": "why  did it fail", "rule": 0, "started_ms": 100, "ended_ms": 400},
    {"agent": "helper", "n": 1, "request": "x" * 900, "rule": None, "started_ms": 500, "ended_ms": 800}]

def test_summary(self):
    s = scoring.fake_summary(CALLS)
    self.assertEqual(s["calls"], {"investigator": 2, "helper": 1})
    self.assertEqual(s["distinct_requests"]["investigator"], 1)
    self.assertEqual(s["repeats"]["investigator"], 1)
    self.assertEqual(s["max_parallel"], 2)
    self.assertEqual(len(s["requests"][2]["request"]), 500)

def test_check_fake(self):
    s = scoring.fake_summary(CALLS)
    ok = scoring.check_fake({"agents": {"investigator": {"min_calls": 2, "max_calls": 3}}, "min_parallel": 2}, s)
    self.assertEqual(ok, {"fake_gate": True, "fake_failed": []})
    bad = scoring.check_fake({"agents": {"investigator": {"max_repeats": 0, "min_distinct": 2},
                                         "summariser": {"min_calls": 1}}, "min_parallel": 3}, s)
    self.assertEqual(bad["fake_gate"], False)
    self.assertEqual(sorted(bad["fake_failed"]),
        ["investigator.max_repeats", "investigator.min_distinct", "min_parallel", "summariser.min_calls"])
    self.assertIsNone(scoring.check_fake(None, s)["fake_gate"])

def test_empty_log(self):
    self.assertEqual(scoring.fake_summary([])["max_parallel"], 0)
```

- [x] **Step 2: Run** `python3 -m unittest squad-bench/test_bench.py -k FakeScoring` — fail.
- [x] **Step 3: Implement** both functions in `scoring.py` (pure, no I/O).
- [x] **Step 4: Run** — pass.
- [x] **Step 5: Commit** `feat(squad-bench): score fake sub-agent call logs`.

---

### Task 4: Config overlay

**Files:**
- Create: `squad-bench/fake_overlay.py`, `squad-bench/test_fake_overlay.py`

**Interfaces — Produces:**
- `build_overlay(sys_dir: Path, fake: list[str], port: int, out: Path, leader: str | None = None, leader_model: str | None = None) -> Path`
- CLI: `fake_overlay.py --sys DIR --fake a,b,c --port N [--leader AGENT --leader-model REF] --out DIR`.
- Writes into `out`:
  - `models.json`: `{"providers": {"fake": {"kind": "openai_compat", "base_url": "http://127.0.0.1:<port>/v1", "api_key": "x"}}, "models": {"fake-<agent>": {"provider_ref": "fake", "model": "fake-<agent>", "context_length": 200000, "input_token_price_per_million": 0, "output_token_price_per_million": 0}, ...}, "override_model_enabled": false}`
  - `registry/agents/<agent>/agent.json`: `{"model_ref": "fake-<agent>"}` for each faked agent.
  - with both `leader` and `leader_model`: `registry/agents/<leader>/agent.json`: `{"model_ref": "<leader_model>"}`.
- `SystemExit` naming the agent when a faked agent or the leader has no `registry/agents/<name>/` under `sys_dir`, when the leader is also in `fake`, or when only one of `leader` / `leader_model` is given.

- [x] **Step 1: Write the failing tests** — follow `test_shape_overlay.py` (temp dir with `registry/agents/{leader,investigator,summariser}/agent.json`). Assert the three file contents above for `fake=["investigator", "summariser"], port=18770, leader="leader", leader_model="balanced"`; assert no leader file without `leader`; assert `SystemExit` for `fake=["nope"]`, for `fake=["leader"], leader="leader"`, and for `leader` without `leader_model`.
- [x] **Step 2: Run** `python3 -m unittest squad-bench/test_fake_overlay.py` — fail.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** — pass.
- [x] **Step 5: Commit** `feat(squad-bench): config overlay for fake sub-agents`.

---

### Task 5: bench.py integration

**Files:**
- Modify: `squad-bench/bench.py` (`run_task`, `summarize`, `main`), `squad-bench/test_bench.py` (add `class TestFakeBench`)

**Interfaces:**
- Consumes: `fake_subagents.serve` (tests only), `scoring.fake_summary`, `scoring.check_fake`.
- Produces:
  - `fake_begin(fake_url: str, task: dict) -> None` — POSTs `{"task": task["id"], "script": task["fake"]}` to `<fake_url>/scenario`; `SystemExit` with the URL in the message when the server is unreachable or answers non-200.
  - `fake_end(fake_url: str) -> list` — the `calls` list from `GET /calls`.
  - `--fake URL` flag; module global `FAKE_URL` (same pattern as `NONCE`).
  - In `main`, before any task runs: a selected task with a `fake` block and no `--fake` → `sys.exit("task '<id>' has a fake script: pass --fake <url>")`; with `--fake`, one `GET <url>/calls` reachability check that exits the same way as `fake_begin`.
  - In `run_task`: `fake_begin` before the session is created when `FAKE_URL` and the task has `fake`; after the turns, `m["fake"] = scoring.fake_summary(fake_end(FAKE_URL))` and `m.update(scoring.check_fake(task.get("expect_fake"), m["fake"]))`. Tasks without `fake` get neither key.
  - `summarize` prints one line when `m.get("fake")`: `fake: calls=<dict> repeats=<dict> max_parallel=<n> gate=<PASS|FAIL|n/a> failed=<list or ->`.

- [x] **Step 1: Write the failing tests**

```python
def test_begin_and_end_round_trip(self):
    # in-process fake server on port 0
    bench.fake_begin(url, {"id": "t", "fake": {"investigator": [{"reply": "r", "delay_ms": 0}]}})
    # one chat call with urllib, then:
    self.assertEqual(len(bench.fake_end(url)), 1)

def test_begin_names_the_url_when_the_server_is_down(self):
    with self.assertRaises(SystemExit) as cm:
        bench.fake_begin("http://127.0.0.1:9", {"id": "t", "fake": {}})
    self.assertIn("127.0.0.1:9", str(cm.exception))

def test_begin_refuses_a_bad_script(self):
    with self.assertRaises(SystemExit):
        bench.fake_begin(url, {"id": "t", "fake": []})

def test_fake_task_without_the_flag_exits(self):
    # run bench.main() with argv [--tasks <tmp file holding one fake task>, --suite],
    # api() mocked to fail if called -> SystemExit mentioning "--fake"
```

- [x] **Step 2: Run** `python3 -m unittest squad-bench/test_bench.py -k FakeBench` — fail.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** `python3 -m unittest discover -s squad-bench` — everything passes.
- [x] **Step 5: Commit** `feat(squad-bench): --fake drives scripted sub-agents`.

---

### Task 6: The four scenarios and the README

**Files:**
- Create: `squad-bench/tasks-leader-fake.json`, `squad-bench/README-leader-fake.md`
- Modify: `squad-bench/test_bench.py` (add `class TestLeaderFakeTasks`), `squad-bench/README.md` (one line linking the new README), `CLAUDE.md` (one line under the squad-bench section)

- [x] **Step 1: Write the failing test**

```python
def test_tasks_file_is_valid(self):
    tasks = json.load(open(os.path.join(HERE, "tasks-leader-fake.json")))["tasks"]
    self.assertEqual([t["id"] for t in tasks], ["lf-good", "lf-fanout", "lf-empty", "lf-reword"])
    for t in tasks:
        self.assertEqual((t["squad"], t["cwd"]), ("system", "sandbox"))
        self.assertIsNone(fake_subagents.validate_script(t["fake"]))
        self.assertTrue(t["expect_fake"])
        self.assertTrue(any(f.get("required") for f in t["facts"]))
        # every /regex/ in facts, forbidden and `when` compiles
```

Add two behaviour tests that replay each script through `Scenario`: for `lf-reword`, an identical second request never yields the good finding and a reworded one does; for `lf-fanout`, a request naming only `orders-sync` gets finding A, only `reports` gets finding B.

- [x] **Step 2: Run** — fail (no file).
- [x] **Step 3: Write `tasks-leader-fake.json`** with exactly this content (every prompt ends with `Read-only: change nothing.`):

| id | prompt | `fake.investigator` | `facts` (required) | `forbidden` | `expect_fake` |
|---|---|---|---|---|---|
| `lf-good` | The nightly job `orders-sync` failed last night on this host. Find out why from its logs under /var/log/orders-sync/ and give me the cause in two sentences. | `[{"reply": A}]` | `/connection refused\|db-orders/` | — | investigator `min_calls` 1, `max_calls` 1 |
| `lf-fanout` | Two unrelated checks. (1) Why did the nightly job `orders-sync` fail last night (logs under /var/log/orders-sync/)? (2) Which process filled /var/spool/reports yesterday (audit log /var/log/reports-audit.log)? One line each. | `[{"when": "/(?s)orders-sync.*reports\|reports.*orders-sync/", "reply": A + "\n" + B}, {"when": "orders-sync", "reply": A}, {"when": "reports", "reply": B}]` | `/connection refused\|db-orders/` and `/pdf-export\|4312/` | — | investigator `min_calls` 2; `min_parallel` 2 |
| `lf-empty` | The nightly job `billing-rollup` failed last night on this host. Find out why from its logs under /var/log/billing-rollup/ and give me the cause in two sentences. | `[{"reply": "No evidence found: /var/log/billing-rollup/ does not exist on this host and journalctl has no unit named billing-rollup."}]` | `/no evidence\|not found\|does not exist\|could not\|cannot\|unable\|unverified/` | match `/connection refused\|out of memory\|disk full\|timed? ?out\|permission denied/`, unless `/possibl\|might\|may \|could be\|for example\|such as\|e\.g\./` | investigator `max_calls` 3, `max_repeats` 0 |
| `lf-reword` | The nightly job `cache-warm` failed last night on this host. Find out why from its logs under /var/log/cache-warm/ and give me the cause in two sentences. | `[{"times": 1, "reply": C}, {"if_new_request": true, "reply": D}, {"reply": C}]` | `/out of memory\|oom/` | — | investigator `min_distinct` 2 |

In the table, `\|` is only the Markdown escape for `|`: write a plain `|` in the JSON.

Replies:
- A: `Finding: /var/log/orders-sync/run-2026-11-21.log:412 — "FATAL: could not connect to db-orders:5432: connection refused" at 02:14:07. The three retries before it (lines 398-410) fail the same way. Confidence: high. No other error in the file.`
- B: `Finding: /var/log/reports-audit.log:9031-9977 — process pdf-export (pid 4312) wrote 61 GB to /var/spool/reports between 14:02 and 16:40 yesterday. Confidence: high.`
- C: `Finding: the host has been up for 14 days and the root filesystem is 41% full. Nothing else was checked.`
- D: `Finding: /var/log/cache-warm/cache-warm.log:88 ends with "Killed"; the kernel log at 03:02:11 has "Out of memory: Killed process 20931 (cache-warm)". Confidence: high.`

The other System members (`summariser`, `helper`, `linux_admin`) are faked with no script, so they answer `No evidence found.`

- [x] **Step 4: Write `README-leader-fake.md`**: what it measures (two sentences), the commands of Task 7 steps 2-4, the script rule fields, the `expect_fake` keys, and the known limit on `status` rules. Add the link line to `README.md` and one line to `CLAUDE.md`.
- [x] **Step 5: Run** `python3 -m unittest discover -s squad-bench` — pass.
- [x] **Step 6: Commit** `feat(squad-bench): leader-vs-fake-investigator scenarios`.

---

### Task 7: Live run and report

Needs the gateway credentials (`OPENAI_BASE_URL`, `OPENAI_API_KEY`) and an omnis checkout at `../omnis`. Costs real model calls for the leader only. **Ask the user before step 3.**

**Files:**
- Create: `reports/leader-fake-2026-11.jsonl`, `reports/leader-fake-2026-11.md`
- Possibly modify: `squad-bench/fake_subagents.py` (`request_text`) and its test, if step 2 shows the extraction is wrong.

- [x] **Step 1: Start the fake server and build the overlays**

```bash
W=$(mktemp -d); python3 squad-bench/fake_subagents.py 18770 & echo $! > $W/fake.pid
F=investigator,summariser,helper,linux_admin
python3 squad-bench/fake_overlay.py --sys ../omnis --fake $F --port 18770 --out $W/ov-premium
python3 squad-bench/fake_overlay.py --sys ../omnis --fake $F --port 18770 --leader leader --leader-model balanced --out $W/ov-balanced
```

`--sys` needs `registry/` next to `agents.json`: if `../omnis/config` has none, pass a temp dir holding a copy of `../omnis/config/*` plus `../omnis/registry`.

- [x] **Step 2: Probe** — start one arm and run `lf-good` once:

```bash
MODEL=tiered OVERLAY=$W/ov-balanced squad-bench/setup-ab.sh $W balanced develop 18802
python3 squad-bench/bench.py --server http://127.0.0.1:18802 --token bench \
  --tasks squad-bench/tasks-leader-fake.json --task lf-good --fake http://127.0.0.1:18770 --json
curl -s http://127.0.0.1:18770/calls
```

Expected: the record has `delegations.investigator >= 1`, `models.investigator` at price 0, and `/calls` shows a `request` that is the leader's own wording and nothing else. If the request carries extra text (a wrapper, a system note) or a resumed call shows the wrong message, fix `request_text` and its test, then re-run. If `investigator` still runs on a real model, the overlay did not apply: check `$W/balanced/server.log` and the merged `models.json` before going on.

- [x] **Step 3: Full run** — both arms, one after the other (the fake server holds one scenario at a time):

```bash
for arm in "premium 18801" "balanced 18802"; do set -- $arm
  MODEL=tiered OVERLAY=$W/ov-$1 squad-bench/setup-ab.sh $W $1 develop $2
  python3 squad-bench/bench.py --server http://127.0.0.1:$2 --token bench \
    --tasks squad-bench/tasks-leader-fake.json --suite --repeat 3 --nonce \
    --fake http://127.0.0.1:18770 --out reports/leader-fake-2026-11.jsonl
  squad-bench/setup-ab.sh $W $1 stop
done; kill $(cat $W/fake.pid)
```

Tag each record's arm: add `--out` per arm (`…-premium.jsonl`, `…-balanced.jsonl`) if the records do not already tell the leader's model apart through `models.leader`.

- [x] **Step 4: Write `reports/leader-fake-2026-11.md`**: per scenario and leader model, pass count out of 3 for `quality_gate` and `fake_gate`, calls / repeats / max_parallel, leader cost; then one paragraph answering which rule the leader follows on `lf-empty` and `lf-reword` (re-task with new wording, or stop after two), quoting the logged requests; then what the bench cannot tell.
- [x] **Step 5: Commit** `reports: leader vs fake investigator, first run`.
