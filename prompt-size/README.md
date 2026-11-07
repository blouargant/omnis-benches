# prompt-size — the fixed prompt of every omnis agent, at no model cost

Every model call re-sends an agent's system instruction and its tool
declarations. This measures that fixed part for the whole agent tree of an
omnis checkout, without calling a real model.

```bash
prompt-size/run.sh ../omnis out-mybranch     # builds ../omnis, writes out-mybranch/
python3 prompt-size/report.py out-mybranch/requests.jsonl -v   # per-tool detail
```

How: `run.sh` copies the checkout's `config/` + `registry/` (+ `softskills/`)
into a temporary system layer, empties the user layer, forces every agent onto a
`probe` model served by `fake_server.py`, and runs one CLI turn per squad
(`OMNIS_START_SQUAD`, the router for `Omnis`). The fake server records every
request and, once per conversation, calls each sub-agent tool it sees with the
request `PROBE:<agent>` — so the sub-agent's first request names it and the whole
tree is reached — then answers "ok". The report lists, per agent, the first
request's instruction tokens, tool count and tool-declaration tokens (chars/4,
the same estimate as the earlier coder measurements).

Rows are agents; squad roots appear under the squad name (first word only:
`Skill` is Skill Editor). A hidden squad cannot be a start squad, so `Session`
shows the router.

Compare two checkouts by running it twice; `out-before/` and `out-after3/` are
the 2026-11-07 fixed-prompt pass (sum 185k → 139k tokens).
