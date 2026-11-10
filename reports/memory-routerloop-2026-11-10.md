# Balanced cut replies: the router loop (2026-11-10)

## Problem

Since the per-message memory reminder, Balanced sometimes produced a reply cut at the 32,768-token output limit. The rate was about 6 in 102 memory_bench steps, against 0 in 42 before the reminder (`memory-narrow-2026-11-10.md`, finding 4). The cut replies held no text.

## Capture

The balanced arm was restarted with `OMNIS_DEBUG=1` (full payloads in the event log) and memory_bench was run until a cut appeared. Two cuts were captured. Both were on the **router** (`omnis`), not on an answering squad, and the router does not get the reminder:

- `"Retiens que le service de facturation écoute sur le port 8443."` produced 32,768 output tokens in 176 s, with no text and no tool call.
- `"Oublie quel outil de suivi des tickets j'utilise…"`: the router called `ask_squad` on helper, then on system. Both answered `CANNOT_HANDLE` ("modifying internal agent memory … falls outside the scope"). The router then reasoned until the limit, 166 s.

A probed lead sees only its instruction, not its tools. No squad description mentions memory, so the leads decline a memory request, and the router ends up with no squad and loops.

## Fixes (omnis)

1. **Routing heuristic** (`registry/agents/omnis/instruction.md`). A request that only asks to remember, correct or forget something goes at once, without `ask_squad`, to the squad the conversation is about, or to the general-purpose squad.
2. **Probe note** (`buildCapabilityCheckPrompt`). Every squad can save, read and delete the collection's memories, so such a request is within its scope.
3. **Empty-cut retry** (`llm.RetryCutToolCall`). A reply cut with no text and no tool call is re-sent once with reasoning off and a short nudge.
   - Fixes 1 and 2 cover the memory case. With them in place, the router still produced two empty cuts on ordinary requests: a commit message, and "sur quel port…".
   - This fix covers any agent.
   - Checked live by forcing `max_output_tokens: 300`: the retry fires and answers.

## Result (balanced memory_bench)

| Build | Score | Cut replies |
|---|---|---|
| narrowed reminder (`memory-narrow`) | 11/15 | 2 |
| + fixes 1, 2 | 26/30 | 2 (router, non-memory requests) |
| + fixes 1, 2, 3 | **27/30** | **0** |

With all three fixes, `update` passes 6/6. The three remaining failures saved the memory correctly and missed only in the answer:

- one `explicit` run;
- one `forget` run that still named the deleted tool;
- one `correction` run.

Steps are also faster, because no 170-second stalls remain.

Raw records: `memory-routerloop-2026-11-10.jsonl` (labels `fix-balanced`, `fix2-balanced`).

High was not re-run. It showed no cuts in any earlier run, and the routing change only affects requests that ask to remember or forget.
