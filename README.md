# omnis-benches

Evaluation and benchmarking tooling for [omnis](https://github.com/blouargant/omnis).
Everything here is **dependency-free** (Python stdlib only) and drives omnis (or a
raw model endpoint) over HTTP — nothing imports omnis, so this repo evolves
independently of the main codebase.

| Tool | What it does |
|---|---|
| [`squad-bench/`](squad-bench/) | Drives a **running omnis-server** like the web UI — create a session pinned to a squad, send one task, stream the SSE — and reduces the event stream to a **metrics record** (latency, streaming granularity, delegations, per-agent model cost, `ask_user`, correctness). Change which **model** an agent runs on (or tighten its instruction) and re-run the same task to compare. |
| [`model-probe/`](model-probe/) | Verifies a live OpenAI-compatible **endpoint + model** supports the features omnis actually uses, with real requests — streamed chat, tool calling (streaming and non-streaming), parameterless tools over streaming, the tool-result round-trip — plus prompt caching / usage / `/model/info` side-info. Exit code is non-zero iff a **critical** check fails. |

`model-probe` tests a *raw endpoint's capabilities*; `squad-bench` tests *squad
behaviour* once that endpoint is wired into omnis. They are sister tools.

## Quick start

```bash
# 1. Is this endpoint usable by omnis at all?
python3 model-probe/probe.py -u "$OPENAI_BASE_URL" -m "$MODEL" -k "$OPENAI_API_KEY"

# 2. How does a squad behave on a task? (needs a running omnis-server)
python3 squad-bench/bench.py --suite
```

Each tool has its own README with the full flag set and metric reference.

## Benches

- **`squad-bench/tasks.json`** — the shipped Coding-squad tasks (search / symbol /
  docs), run against the tiny git-isolated `squad-bench/sandbox/` Go module.
- **`squad-bench/tasks-kubernetes.json`** + **[`squad-bench/README-kubernetes.md`](squad-bench/README-kubernetes.md)**
  — a model-tier sweep for the Kubernetes squad's `k8s_editor` / `k8s_cleaner`
  sub-agents (ownership detection, the "don't break Helm" guard, cleanup scoping),
  including the leaderless-solo-squad + `models.json`-override methodology.

New benches are added here as a tasks file (+ a short README when they need
fixtures or a special setup), following the same shape.
