#!/usr/bin/env python3
"""
squad-bench — measure how an omnis squad handles a task, for benchmarking
different models on different tasks.

Dependency-free (Python stdlib only), mirroring model-probe/probe.py.

It drives the running omnis-server HTTP API exactly like the web UI does:
create a session pinned to a squad, send one task prompt, stream the SSE, and
reduce the event stream to a metrics record — so you can change an agent's
model (via Settings / config + reload) and re-run the same task to compare.

What it measures per run
------------------------
  wall_ms / ttfb_ms      total time, and time to first content event
  token_events           # of streamed `token` frames  (high => model streams
                         token-by-token; ~1-3 => coarse/buffered/non-streaming)
  delegated / redispatches  did the leader call sub-agents, and did it call the
                         SAME sub-agent more than once (a retry / flailing signal)
  leader_tools           {tool: count} the leader called directly
  subagent_tools         {agent: {tool: count}} each sub-agent ran internally
  models                 {agent: {in$/M, out$/M, prompt_tok, out_tok, calls,
                         est_cost_usd}}  (price IS the model's identity here)
  subagent_errors        sub-agent results that were empty or carried an error
                         (e.g. "context deadline exceeded" == endpoint too slow)
  ask_user               # of permission prompts the run raised (want 0 for a
                         squad whose read-only members are allow-listed)
  correct                if the task declares `expect`, whether the final answer
                         matched (substring, or /regex/)
  status                 done | timeout | cancelled | error

Usage
-----
  python3 bench.py --suite                      # run tasks.json against defaults
  python3 bench.py --task search-single         # one task by id
  python3 bench.py --suite --repeat 3           # 3 samples each (models vary run-to-run)
  python3 bench.py --task search-single --json  # machine-readable record only
  python3 bench.py --suite --out results.jsonl  # append one JSON record per run

  # Bench a different model: change the agent's model_ref (Settings → Agent, or
  # edit models.json / agent.json + POST /api/config/reload), then re-run the
  # same task. The `models` block in each record captures which model was active.

Env / flags: --server (default http://127.0.0.1:8080), --token (or
OMNIS_SERVER_TOKEN), --deadline seconds per turn (default 420), --keep (don't delete the
session), --cwd (override task cwd).
"""
import argparse
import uuid
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import scoring

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------- HTTP / SSE
def _req(method, base, path, token, body=None, timeout=600):
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    return urllib.request.urlopen(r, timeout=timeout)


def api(method, base, path, token, body=None, timeout=60):
    with _req(method, base, path, token, body, timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def iter_sse(resp):
    """Yield (seq:int|None, event:str, data:dict) frames from an SSE stream."""
    seq = ev = None
    buf = []
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line == "":
            if ev is not None:
                blob = "\n".join(buf)
                try:
                    data = json.loads(blob) if blob else {}
                except Exception:
                    data = {"_raw": blob}
                yield seq, ev, data
            seq = ev = None
            buf = []
            continue
        if line.startswith("id:"):
            try:
                seq = int(line[3:].strip())
            except ValueError:
                pass
        elif line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            buf.append(line[5:].lstrip())


# ----------------------------------------------------------------------------- metrics
def fresh():
    return {
        "status": "error",
        "ttfb_ms": None,
        "token_events": 0,
        "leader_tools": {},
        "subagent_tools": {},          # agent -> {tool: count}
        "delegations": {},             # agent -> count (leader called it)
        "models": {},                  # agent -> usage/cost
        "subagent_errors": [],
        "ask_user": 0,
        "answer": "",
        "_answer_parts": [],
        "_seq": 0,
        "_urls": set(),
    }


def note_model(m, u):
    a = u.get("agent") or "?"
    e = m["models"].setdefault(
        a, {"in_per_m": u.get("in_price_per_m"), "out_per_m": u.get("out_price_per_m"),
            "prompt_tok": 0, "out_tok": 0, "cache_read_tok": 0, "calls": 0, "est_cost_usd": 0.0})
    prompt_tokens = u.get("prompt_tokens") or 0
    cache_read_tokens = u.get("cache_read_tokens") or 0
    e["prompt_tok"] += prompt_tokens
    e["out_tok"] += u.get("output_tokens") or 0
    e["cache_read_tok"] += cache_read_tokens
    e["calls"] += 1
    inp = (u.get("in_price_per_m") or 0) / 1e6
    outp = (u.get("out_price_per_m") or 0) / 1e6
    crp = (u.get("cache_read_price_per_m") or 0) / 1e6
    # prompt_tokens (OpenAI usage convention) already INCLUDES cache_read_tokens
    # as a subset, not an addition -- billing both the full prompt count at the
    # input price AND cache_read_tokens at the cache-read price double-charges
    # the cached portion. Only the uncached remainder pays the full input price;
    # cache_read_tokens pay the (usually much cheaper) cache-read price. Clamp
    # at zero defensively: a provider report where cache_read > prompt would
    # otherwise go negative.
    uncached_tokens = max(0, prompt_tokens - cache_read_tokens)
    e["est_cost_usd"] = round(
        e["est_cost_usd"]
        + uncached_tokens * inp
        + cache_read_tokens * crp
        + (u.get("output_tokens") or 0) * outp, 6)


def _note_url(m, args):
    """Record a URL a tool was asked to fetch, so source coverage can be
    compared across variants. Answers barely cite URLs (0/0/1 across the DS7
    trace), so the answer text is useless for this — the tool args are not."""
    if not isinstance(args, dict):
        return
    u = args.get("url") or args.get("URL")
    if isinstance(u, str) and u.startswith(("http://", "https://")):
        m["_urls"].add(u)


def fetch_count(m):
    """WebFetch calls across the leader and every sub-agent."""
    n = m["leader_tools"].get("WebFetch", 0)
    for tools in m["subagent_tools"].values():
        n += tools.get("WebFetch", 0)
    return n


ANSWER_ASKS = False
NONCE = False
FAKE_URL = ""     # --fake: a fake_subagents.py server answering for the sub-agents


class FakeError(Exception):
    """The fake sub-agent server could not be used; str() says why."""


def _fake_call(fake_url, path, body=None):
    url = fake_url.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        e.close()
        raise FakeError(f"fake sub-agent server {url} answered HTTP {e.code}: {detail}")
    except (OSError, ValueError) as e:
        raise FakeError(f"fake sub-agent server {url} is not reachable: {e}")


def fake_begin(fake_url, task):
    """Give the fake sub-agent server this task's script (none: every call gets
    the default reply); its call log restarts. Returns the run's token, which
    fake_end checks, so a log written by another run is never scored as this one's."""
    token = f"{task['id']}#{uuid.uuid4().hex[:8]}"
    try:
        _fake_call(fake_url, "/scenario", {"task": token, "script": task.get("fake", {})})
    except FakeError as e:
        sys.exit(str(e))
    return token


def fake_end(fake_url, token=None):
    """The calls the sub-agents received since fake_begin. Raises FakeError when
    the server is gone or now holds another run's scenario."""
    out = _fake_call(fake_url, "/calls")
    if token and out.get("task") != token:
        raise FakeError(f"fake sub-agent server {fake_url} now holds the scenario of another run "
                        f"({out.get('task')!r}, expected {token!r}): this run's calls are lost")
    return out.get("calls") or []


def fake_record(fake_url, task, m, token=None):
    """Add the call summary and the `expect_fake` verdict to a run record. A log
    that cannot be read is reported in `fake_error`, never scored."""
    try:
        m["fake"] = scoring.fake_summary(fake_end(fake_url, token))
    except FakeError as e:
        m["fake"], m["fake_error"] = None, str(e)
        m["fake_gate"], m["fake_failed"] = False, ["fake_error"]
        return
    m.update(scoring.check_fake(task.get("expect_fake"), m["fake"]))
ASK_REPLY = "No preference - use your own best judgment and continue without asking me again."


def consume(resp, m, agents, t0, deadline):
    """Fold an SSE stream into m. Return True once a `done` frame is seen."""
    for seq, ev, d in iter_sse(resp):
        if seq is not None:
            m["_seq"] = max(m["_seq"], seq)
        if ev in ("token", "message"):
            if m["ttfb_ms"] is None:
                m["ttfb_ms"] = int((time.time() - t0) * 1000)
            if ev == "token":
                m["token_events"] += 1
            txt = d.get("text") or d.get("message") or ""
            if txt:
                m["_answer_parts"].append(txt)
        elif ev == "tool_call":
            name = d.get("name") or "?"
            if name in agents:                       # leader delegating to a sub-agent
                m["delegations"][name] = m["delegations"].get(name, 0) + 1
            else:
                m["leader_tools"][name] = m["leader_tools"].get(name, 0) + 1
            _note_url(m, d.get("args"))
        elif ev == "agent_tool_call":
            a = d.get("agent") or "?"
            t = d.get("name") or "?"
            m["subagent_tools"].setdefault(a, {})
            m["subagent_tools"][a][t] = m["subagent_tools"][a].get(t, 0) + 1
            _note_url(m, d.get("args"))
        elif ev == "tool_result":
            _scan_subagent_result(m, d, agents)
        elif ev == "turn_usage":
            note_model(m, d)
        elif ev == "ask_user":
            # omnis forwards every session's questions into each live turn
            # stream; with several sessions on one server, answering another
            # session's question 404s for all but the first client and used to
            # abandon this task. Only our own session's questions count.
            qsid = d.get("session_id")
            if qsid and m.get("_sid") and qsid != m["_sid"]:
                continue
            m["ask_user"] += 1
            # Keep what was asked: "status=ask_user" alone does not say which
            # command needs allow-listing.
            m["ask_detail"] = {k: d.get(k) for k in ("question", "prompt", "title", "tool", "args", "reason") if d.get(k)}
            if m.get("_answer_asks") and d.get("question_id"):
                # --answer-asks: play a hands-off user instead of aborting.
                # A subtle (optional, closing) question is skipped; any other
                # question gets "no preference, decide yourself".
                m.setdefault("asks_answered", []).append((d.get("prompt") or "")[:200])
                if d.get("subtle"):
                    body = {"cancelled": True}
                elif d.get("choices") and not d.get("allow_text"):
                    body = {"selected": [d.get("default") or d["choices"][0]]}
                else:
                    body = {"text": ASK_REPLY}
                try:
                    api("POST", m["_base"], f"/api/sessions/{m['_sid']}/ask-user/{d['question_id']}", m["_token"], body)
                    continue
                except urllib.error.HTTPError as e:
                    if e.code == 404:  # already answered or cancelled: keep streaming
                        continue
                    m["ask_detail"]["answer_error"] = str(e)
                except Exception as e:  # fall back to aborting, as without the flag
                    m["ask_detail"]["answer_error"] = str(e)
            # The bench can never answer a prompt, so streaming on only burns the
            # deadline and then reports `cancelled` — which reads like a model
            # failure instead of "a tool call asked for confirmation". Stop here
            # and name it. Returning True also stops run_one_turn reconnecting.
            m["status"] = "ask_user"
            return True
        elif ev == "done":
            m["status"] = "done"
            return True
        if time.time() - t0 > deadline:
            return False
    return False


def _scan_subagent_result(m, d, agents):
    name = d.get("name") or d.get("tool") or ""
    if name not in agents:
        return
    resp = d.get("response")
    blob = json.dumps(resp) if not isinstance(resp, str) else resp
    low = blob.lower()
    empty = (not blob) or blob in ("{}", '{"results": []}', '{"results":[]}')
    if empty or "deadline exceeded" in low or '"error"' in low or "timeout" in low:
        snippet = blob[:200] if blob else "(empty result)"
        m["subagent_errors"].append({"agent": name, "detail": snippet})


# ----------------------------------------------------------------------------- run one task
def prepare_cwd(task, override):
    if override:
        return override, None
    # ${VAR} expansion lets a tasks file point at fixtures built outside the
    # repo (e.g. ${TOKOPT_DIR}/gofail from setup-tokopt.sh). An unset variable
    # would leave a literal "${...}" path the server rejects, so fail loudly.
    cwd = os.path.expandvars(task.get("cwd", ""))
    if "$" in cwd:
        raise SystemExit(f"task {task.get('id')!r}: unresolved variable in cwd {cwd!r}")
    if cwd == "sandbox":
        src = os.path.join(HERE, "sandbox")
        tmp = tempfile.mkdtemp(prefix="squadbench-")
        for f in os.listdir(src):
            shutil.copy2(os.path.join(src, f), tmp)
        try:  # isolate + make any accidental edit trivially revertible
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=False)
            subprocess.run(["git", "add", "-A"], cwd=tmp, check=False)
            subprocess.run(["git", "-c", "user.email=b@b", "-c", "user.name=b",
                            "commit", "-qm", "seed"], cwd=tmp, check=False)
        except Exception:
            pass
        return tmp, tmp
    return cwd or os.getcwd(), None


def task_prompts(task):
    """A task declares `prompts: [...]` (multi-turn) or `prompt` (single turn).

    The costly turn in the DS7 trace was a follow-up — the leader already held
    context — so reproducing that shape needs more than one POST on one session.
    """
    if task.get("prompts"):
        return list(task["prompts"])
    return [task["prompt"]]


def run_one_turn(base, token, sid, prompt, m, agents, deadline):
    """POST one prompt and fold its SSE stream into `m`. True once `done` seen.

    `deadline` is per turn: a 3-turn task gets 3× the budget of a 1-turn task,
    which keeps single-turn behaviour byte-identical to before.
    """
    t0 = time.time()
    done = False
    try:
        resp = _req("POST", base, f"/api/sessions/{sid}/messages", token,
                    {"prompt": prompt}, timeout=deadline)
        done = consume(resp, m, agents, t0, deadline)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        pass
    while not done and time.time() - t0 < deadline:
        try:
            resp = _req("GET", base,
                        f"/api/sessions/{sid}/messages/stream?from={m['_seq']}",
                        token, timeout=deadline)
            if getattr(resp, "status", 200) == 204:
                m["status"] = "done"
                return True
            done = consume(resp, m, agents, t0, deadline)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(1)
    return done


def run_task(base, token, task, agents, deadline, keep, cwd_override):
    fake_token = fake_begin(FAKE_URL, task) if FAKE_URL else None
    cwd, tmp = prepare_cwd(task, cwd_override)
    sess = api("POST", base, "/api/sessions", token,
               {"squad": task["squad"], "dir": cwd, "name": "bench-" + task["id"]})
    sid = sess.get("session_id") or sess.get("id")
    m = fresh()
    m["task"] = task["id"]
    m["squad"] = task["squad"]
    m["cwd"] = cwd
    m["session_id"] = sid
    m["_base"], m["_sid"], m["_token"] = base, sid, token
    m["_answer_asks"] = ANSWER_ASKS
    t0 = time.time()
    m["answers"] = []
    done = True
    m["prompts"] = task_prompts(task)
    if NONCE:
        # The ChapsVision gateway caches responses: a repeat of an identical
        # request comes back in seconds with the same answer, so every sample
        # after the first measured nothing. A unique tag on the first prompt
        # makes each run's requests distinct.
        m["prompts"][0] += f"\n\n(bench run {uuid.uuid4().hex[:8]})"
    for prompt in m["prompts"]:
        mark = len(m["_answer_parts"])
        done = run_one_turn(base, token, sid, prompt, m, agents, deadline)
        m["answers"].append("".join(m["_answer_parts"][mark:]).strip())
        if not done or m["status"] == "ask_user":
            break
    if m["status"] == "ask_user":
        # The turn "finished" only in the sense that we stopped listening. The
        # session is still sitting on the prompt, so release it — and keep the
        # status, which says far more than `cancelled` would.
        try:
            api("POST", base, f"/api/sessions/{sid}/cancel", token, {})
        except Exception:
            pass
    elif not done:
        m["status"] = "timeout"
        try:
            api("POST", base, f"/api/sessions/{sid}/cancel", token, {})
            m["status"] = "cancelled"
        except Exception:
            pass
    m["wall_ms"] = int((time.time() - t0) * 1000)
    m["redispatches"] = sum(v - 1 for v in m["delegations"].values() if v > 1)
    m["answer"] = "\n\n".join(a for a in m["answers"] if a).strip()
    m["total_cost_usd"] = round(sum(x["est_cost_usd"] for x in m["models"].values()), 6)
    m["correct"] = check_expect(task.get("expect"), m["answer"])
    m.update(scoring.quality_gate(task, m["answers"]))
    if FAKE_URL:
        fake_record(FAKE_URL, task, m, fake_token)
    m["distinct_urls"] = len(m["_urls"])
    m["fetches"] = fetch_count(m)
    m["facts_per_fetch"] = (round(len(m["facts"]["found"]) / m["fetches"], 3)
                            if m["fetches"] else None)
    for k in ("_answer_parts", "_seq", "_urls", "_base", "_sid", "_token", "_answer_asks"):
        m.pop(k, None)
    if not keep and sid:
        try:
            api("DELETE", base, f"/api/sessions/{sid}", token)
        except Exception:
            pass
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return m


def check_expect(expect, answer):
    if not expect:
        return None
    if expect.startswith("/") and expect.endswith("/") and len(expect) > 1:
        return bool(re.search(expect[1:-1], answer or "", re.I))
    return (expect.lower() in (answer or "").lower())


# ----------------------------------------------------------------------------- output
def summarize(m):
    ok = {True: "PASS", False: "FAIL", None: "n/a"}[m.get("correct")]
    print(f"\n=== {m['task']}  [squad={m['squad']}]  status={m['status']}  correct={ok} ===")
    print(f"  wall={m['wall_ms']}ms  ttfb={m['ttfb_ms']}ms  token_events={m['token_events']}"
          f"  ask_user={m['ask_user']}")
    if m["delegations"]:
        deleg = ", ".join(f"{a}×{n}" for a, n in m["delegations"].items())
        print(f"  delegated: {deleg}   redispatches={m['redispatches']}")
    else:
        print("  delegated: (none — leader did it itself)")
    for a, u in m["models"].items():
        print(f"  model[{a}]: ${u['in_per_m']}/{u['out_per_m']} per M"
              f"  tok={u['prompt_tok']}in/{u['out_tok']}out  calls={u['calls']}"
              f"  ~${u['est_cost_usd']}")
    print(f"  total est cost: ${m['total_cost_usd']}")
    if m["subagent_tools"]:
        for a, tools in m["subagent_tools"].items():
            print(f"  {a} ran: " + ", ".join(f"{t}×{n}" for t, n in tools.items()))
    if m["subagent_errors"]:
        print(f"  ⚠ sub-agent errors ({len(m['subagent_errors'])}):")
        for e in m["subagent_errors"][:3]:
            print(f"      {e['agent']}: {e['detail']}")
    gate = {True: "PASS", False: "FAIL", None: "n/a"}[m.get("quality_gate")]
    f = m.get("facts") or {}
    print(f"  quality_gate={gate}  facts={len(f.get('found', []))}/{f.get('required', 0)}"
          f"  missing={f.get('missing') or '-'}  forbidden={m.get('forbidden_hits') or '-'}")
    if m.get("fake_error"):
        print(f"  fake: ERROR {m['fake_error']}")
    if m.get("fake"):
        fk = m["fake"]
        fgate = {True: "PASS", False: "FAIL", None: "n/a"}[m.get("fake_gate")]
        print(f"  fake: calls={fk['calls']}  repeats={fk['repeats']}  near_repeats={fk['near_repeats']}  max_parallel={fk['max_parallel']}"
              f"  gate={fgate}  failed={m.get('fake_failed') or '-'}")
    print(f"  fetches={m.get('fetches')}  distinct_urls={m.get('distinct_urls')}"
          f"  facts_per_fetch={m.get('facts_per_fetch')}")
    ans = (m["answer"] or "").replace("\n", " ")
    print(f"  answer: {ans[:180]}")


def main():
    ap = argparse.ArgumentParser(description="Benchmark an omnis squad on a task.")
    ap.add_argument("--server", default=os.environ.get("OMNIS_SERVER", "http://127.0.0.1:8080"))
    ap.add_argument("--token", default=os.environ.get("OMNIS_SERVER_TOKEN", ""))
    ap.add_argument("--tasks", default=os.path.join(HERE, "tasks.json"))
    ap.add_argument("--task", help="run a single task by id")
    ap.add_argument("--suite", action="store_true", help="run every task in the file")
    ap.add_argument("--repeat", type=int, default=1, help="samples per task")
    ap.add_argument("--deadline", type=int, default=420, help="per-turn wall-clock cap (s)")
    ap.add_argument("--cwd", help="override the task working directory")
    ap.add_argument("--keep", action="store_true", help="don't delete the bench session")
    ap.add_argument("--out", help="append one JSON record per run to this file")
    ap.add_argument("--json", action="store_true", help="print JSON records only")
    ap.add_argument("--answer-asks", action="store_true",
                    help="answer AskUserQuestion prompts ('no preference') instead of aborting the run")
    ap.add_argument("--nonce", action="store_true",
                    help="append a unique run tag to the first prompt (defeats the gateway response cache across --repeat samples)")
    ap.add_argument("--fake", default="",
                    help="URL of a fake_subagents.py server: tasks with a `fake` script run against it")
    args = ap.parse_args()
    global ANSWER_ASKS, NONCE, FAKE_URL
    ANSWER_ASKS = args.answer_asks
    NONCE = args.nonce
    FAKE_URL = args.fake

    with open(args.tasks) as f:
        catalog = json.load(f)["tasks"]
    if args.task:
        sel = [t for t in catalog if t["id"] == args.task]
        if not sel:
            sys.exit(f"no task '{args.task}' in {args.tasks}")
    elif args.suite:
        sel = catalog
    else:
        sys.exit("choose --suite or --task <id>  (list: "
                 + ", ".join(t["id"] for t in catalog) + ")")

    scripted = [t["id"] for t in sel if "fake" in t]
    if scripted and not FAKE_URL:
        sys.exit(f"task '{scripted[0]}' has a fake script: pass --fake <url>")
    if FAKE_URL:
        try:   # fail now, not after the first session, when the server is down
            fake_end(FAKE_URL)
        except FakeError as e:
            sys.exit(str(e))

    # all agent names across all squads => used to classify a leader tool_call as a delegation
    squads = api("GET", args.server, "/api/squads", args.token)
    agents = set()
    for s in squads.get("squads", []):
        agents.update(s.get("members", []))
        if s.get("leader"):
            agents.add(s["leader"])

    records = []
    for task in sel:
        for i in range(args.repeat):
            m = run_task(args.server, args.token, copy.deepcopy(task),
                         agents, args.deadline, args.keep, args.cwd)
            if args.repeat > 1:
                m["sample"] = i + 1
            records.append(m)
            if args.json:
                print(json.dumps(m))
            else:
                summarize(m)
            if args.out:
                with open(args.out, "a") as f:
                    f.write(json.dumps(m) + "\n")

    if not args.json and len(records) > 1:
        print("\n===== summary =====")
        for m in records:
            tag = {True: "PASS", False: "FAIL", None: " -- "}[m.get("correct")]
            print(f"  [{tag}] {m['task']:<16} {m['status']:<9} {m['wall_ms']:>6}ms"
                  f"  ${m['total_cost_usd']:<8} tok_ev={m['token_events']:<4}"
                  f" redispatch={m.get('redispatches',0)}")


if __name__ == "__main__":
    main()
