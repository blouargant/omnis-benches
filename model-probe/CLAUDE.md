# model-probe — guidance for Claude (and humans) maintaining this suite

This folder is a **standalone, dependency-free test suite** that verifies a live
OpenAI-compatible endpoint + model supports the features **Omnis** actually uses.
You give it an endpoint, a model id and a key; it fires **real requests** and
reports, per feature, whether it works — plus side information (caching, thinking
models, usage accounting, …).

It is intentionally **decoupled** from the Go codebase: pure Python standard
library, no build step, no `pip install`. That is a hard constraint — keep it so.

## Why this exists

Omnis is provider-agnostic: the same binary runs against any OpenAI-compatible
gateway (LiteLLM, Scaleway, vLLM, Ollama, OpenAI, …). Whether a given model
*actually* supports the features Omnis depends on (streamed tool calls,
parameterless tools, tool-result round-trips, prompt caching, …) can only be known
by **probing the real endpoint**. This suite is that probe. It was born from a real
incident: GLM-5.2 on Scaleway silently drops streamed tool calls for parameterless
tools (works non-streamed) — see `../../glm-5.2-streaming-bug.md`. The
`Parameterless tool over streaming` check encodes exactly that regression.

## Run it

```bash
python3 probe.py --base-url https://api.scaleway.ai/v1 --model glm-5.2 --key "$KEY"
python3 probe.py -u "$OPENAI_BASE_URL" -m glm-5.2-scaleway -k "$OPENAI_API_KEY" -v   # verbose
python3 probe.py ... --only tools                  # one category
python3 probe.py ... --embeddings -m my-embed-model # opt-in embeddings checks
python3 probe.py ... --json > report.json          # machine-readable
python3 probe.py --list                            # list all checks + what they validate
```

Credentials fall back to env vars when flags are omitted:
`OMNIS_PROBE_BASE_URL|OPENAI_BASE_URL|SCALEWAY_API_BASE_URL`,
`OMNIS_PROBE_API_KEY|OPENAI_API_KEY|SCALEWAY_API_KEY`,
`OMNIS_PROBE_MODEL|OMNIS_MODEL`.

`base_url` must include the version path (e.g. `.../v1`), exactly like Omnis's
`OPENAI_BASE_URL`. The client appends `/chat/completions`, `/embeddings`,
`/models`, `/model/info`.

Exit code is **non-zero** iff a **critical** check FAILs or ERRORs.

## Layout

```
model-probe/
├── probe.py          # CLI + runner + report (no checks live here)
├── core.py           # framework: Client, ChatResult, Result, @check registry
├── checks/
│   ├── __init__.py   # AUTO-DISCOVERS every non-underscore module — no wiring
│   ├── _helpers.py   # shared tools/prompts/fixtures (underscore => not a check module)
│   ├── chat.py       # baseline chat + streaming + system instruction
│   ├── tools.py      # tool calling (ns / streaming / parameterless / round-trip / parallel)
│   ├── params.py     # usage, usage-in-stream, max_tokens, temperature
│   ├── caching.py    # prompt-cache detection (INFO)
│   ├── reasoning.py  # thinking-model / reasoning_content detection (INFO)
│   ├── meta.py       # /models and LiteLLM /model/info (INFO)
│   ├── embeddings.py # opt-in: /embeddings (run with --embeddings)
│   └── vision.py     # opt-in: image_url multimodal input (run with --vision)
└── README.md
```

## How to add a check (the common task)

1. Pick (or create) a module under `checks/`. **A new file is auto-discovered** —
   you do **not** edit `__init__.py`. (Files starting with `_` are skipped.)
2. Write a function `def my_check(client) -> Result` and decorate it:

```python
from core import check, Result, PASS, FAIL, WARN, INFO

@check("Short human title", category="tools", critical=True,
       why="One line: which Omnis feature this validates.")
def my_check(client):
    r = client.chat(
        messages=[{"role": "user", "content": "..."}],
        tools=[...],            # optional
        tool_choice="auto",     # optional
        stream=True,            # True exercises the SSE path
    )
    if r.error:
        return Result(FAIL, "request failed: %s" % r.error[:200])
    if <feature works>:
        return Result(PASS, "what worked")
    return Result(FAIL, "what's broken", data={"finish_reason": r.finish_reason})
```

That's it — `probe.py` picks it up on the next run.

### The `@check` contract

| arg | meaning |
|---|---|
| `name` | title shown in the report |
| `category` | report grouping; also the `--only`/`--skip` key. New category? add it to `CATEGORY_ORDER` in `probe.py` for ordering (optional). |
| `critical` | `True` → a FAIL/ERROR here fails the whole run (non-zero exit). Use for features Omnis cannot work without. `False` → informational, never fails the run. |
| `why` | one line mapping the check to the Omnis feature it guards. Shown with `--list` and `-v`. **Always fill this in.** |

A check returns a single `Result` (or a `list[Result]`). If it raises, the runner
catches it and records an `ERROR` — don't wrap everything in try/except yourself,
but DO turn *expected* failures (HTTP 4xx, missing field) into a clean
`Result(FAIL, ...)` with a helpful message.

### Result statuses (`from core import ...`)

| status | use for |
|---|---|
| `PASS` | feature works as Omnis expects |
| `FAIL` | feature broken/unsupported (fails the run if `critical`) |
| `WARN` | partial / weak / intermittent / endpoint quirk |
| `INFO` | side information, **no judgement** (caching present? thinking model? pricing?) |
| `SKIP` | not applicable |

Put **side-information checks at `INFO`**, not PASS/FAIL — e.g. "caching active",
"thinking model", "parallel tool calls supported". The run shouldn't fail just
because an optional capability is absent.

### The `Client` / `ChatResult` API (in `core.py`)

`client.chat(messages, tools=None, tool_choice=None, stream=False, **extra)` →
`ChatResult`. Extra kwargs pass straight into the request body
(`temperature=`, `max_tokens=`, …). Also: `client.get_json(path)`,
`client.post_json(path, body)` → `(status_code, parsed|text)`.

`ChatResult` fields you'll use:

| field | notes |
|---|---|
| `ok` / `error` / `status_code` | `error` is set (and `ok=False`) on HTTP/transport failure |
| `text` | concatenated assistant text (string or array content) |
| `tool_calls` / `tool_call_names` | `[{"id","name","arguments"}]` / `["name", ...]` |
| `finish_reason` | `"stop"`, `"tool_calls"`, `"length"`, … |
| `reasoning` | `reasoning_content` (thinking models) |
| `usage` / `cached_tokens` | token accounting; `cached_tokens` normalizes the cache fields |
| **streaming only** | `streamed`, `saw_text_delta`, `saw_tool_call_delta`, `n_chunks`, `ttft`, `elapsed` |

For the streaming path, judge tool-call support with **`saw_tool_call_delta`** +
`tool_call_names`, and a streaming text issue with `saw_text_delta` / `n_chunks` —
**don't** assume a parsed `tool_calls` implies it streamed.

### Conventions & gotchas

- **Stdlib only.** No `requests`, no third-party deps. If you reach for one, stop.
- **Sample flaky behaviors.** Tool-call *decisions* vary run-to-run. For
  capability checks, sample N times (see `SAMPLES` in `tools.py`) and report a
  fraction: all → PASS, none → FAIL, some → WARN. Don't let a lucky single sample
  hide a real regression (this is how the GLM bug was made deterministic).
- **Make prompts force the behavior.** If you test tool calling, tell the model to
  use the tool, and prefer `tool_choice="auto"` (or `"required"` to force). A
  PASS/FAIL should reflect *transport/support*, not the model's mood.
- **Streaming is where bugs hide.** Always add a streaming variant of any
  tool/feature check — Omnis streams every turn. Several real faults (dropped tool
  calls, dropped reasoning) only appear with `stream=True`.
- **Opt-in categories.** `embeddings` and `vision` only run with their flag
  (they need a model of that kind). To add another opt-in category, add its name to
  `OPT_IN_CATEGORIES` in `probe.py` and a `--flag` that enables it.
- **Keep `why` honest and specific** — it's the link back to the Omnis feature, and
  it's what makes a failing report actionable (e.g. the parameterless check tells
  the user to set `disable_streaming`).

## Feature → check map (keep current when Omnis's model usage changes)

| Omnis feature (see ../../CLAUDE.md) | check(s) |
|---|---|
| Streamed chat to the UI | `chat: Streaming chat completion` |
| Agent tool calling | `tools: Tool calling (non-streaming / streaming)` |
| Parameterless tools (`list_skills`, …) over stream | `tools: Parameterless tool over streaming` |
| Tool loop (role:tool round-trip) | `tools: Tool result round-trip` |
| Router / forcing a tool | `tools: tool_choice=required` |
| Cost & cache stats | `params: Usage *`, `caching: Prompt caching` |
| Thinking models (GLM/DeepSeek/o1) | `reasoning: Reasoning content` |
| Web UI model picker / prefills | `meta: /models`, `meta: /model/info` |
| Semantic recall embedder | `embeddings: *` (opt-in) |
| Image attachments | `vision: Image input` (opt-in) |

When Omnis starts depending on a new model capability, add a check here and a row
above.
