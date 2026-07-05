# model-probe

Verify that an OpenAI-compatible **endpoint + model** supports the features
[Omnis](../../CLAUDE.md) actually uses — with **real requests** against the live
endpoint. Pure Python standard library: **no install, no dependencies**.

```bash
python3 probe.py --base-url https://api.scaleway.ai/v1 --model glm-5.2 --key "$KEY"
```

It checks streamed chat, tool calling (non-streaming **and** streaming),
**parameterless tools over streaming** (a real-world fault — see
[`../../glm-5.2-streaming-bug.md`](../../glm-5.2-streaming-bug.md)), the tool-result
round-trip, and reports side information: prompt caching, thinking-model
`reasoning_content`, token usage, `/models`, LiteLLM `/model/info`. Embeddings and
vision checks are opt-in.

## Usage

```bash
python3 probe.py -u <base_url> -m <model> -k <key> [options]

  -u, --base-url   endpoint incl. version path, e.g. https://api.scaleway.ai/v1
  -m, --model      model id to test
  -k, --key        API key (Bearer)
      --header K:V  extra request header (repeatable)
      --only cats   comma-separated categories (chat,tools,params,caching,reasoning,meta)
      --skip cats   comma-separated categories to skip
      --embeddings  run embeddings checks (point -m at an embedding model)
      --vision      run vision checks (point -m at a vision model)
      --json        machine-readable output
  -v, --verbose     show each check's rationale + data
      --list        list all checks and what they validate
```

Credentials fall back to env vars when flags are omitted:
`OPENAI_BASE_URL`/`SCALEWAY_API_BASE_URL`, `OPENAI_API_KEY`/`SCALEWAY_API_KEY`,
`OMNIS_MODEL`. Exit code is non-zero iff a **critical** check fails.

## Example

```
  TOOLS
    PASS  * Tool calling (non-streaming)       tool call returned (finish_reason=tool_calls)
    PASS  * Tool calling (streaming)           tool call received over the stream (3/3)
    FAIL  * Parameterless tool over streaming  parameterless tool LOST in streaming (0/3) but works
                                               non-streaming → set disable_streaming for this model in Omnis
    PASS  * Tool result round-trip             model consumed the tool result and answered
  ...
  8 pass  1 fail  1 warn  7 info
  FEATURES BROKEN — see critical (*) failures above
```

`*` marks **critical** features (Omnis can't work without them).

## Adding tests

Drop a `checks/<name>.py` file with `@check(...)`-decorated functions — it is
auto-discovered, no wiring. See [CLAUDE.md](CLAUDE.md) for the full guide and the
feature→check map.
```
