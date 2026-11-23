# GEPA run `leader-system` — 2026-11-23

Components: instruction:leader, turn_reminder:leader. Models: balanced, premium (search on balanced).

Spend: $12.63 (eval $10.35, keep_check $0.10, reflection $2.18).

## Held-out verdict

Adopt: **no** — no (agent, model) below the baseline's 90 % interval and at least one above it.

| agent | model | baseline | 90 % interval | candidate | verdict |
|---|---|---|---|---|---|
| leader | balanced | 0.978 | 0.933–1.0 | 0.978 | same |
| leader | premium | 1.0 | 1.0–1.0 | 0.978 | worse |

## Validation scores of the candidates

| candidate | val score |
|---|---|
| 0 | 0.900 |
| 1 | 0.800 |
| 2 | 0.900 |
| 3 | 1.000 |
| 4 | 0.900 |
| 5 | 1.000 |
| 6 | 1.000 |
| 7 | 1.000 |
| 8 | 0.900 |
| 9 | 0.900 |
| 10 | 0.900 |
| 11 | 0.800 |
| 12 | 1.000 |
| 13 | 0.800 |
| 14 | 1.000 |
| 15 | 0.800 |
| 16 | 0.900 |
| 17 | 1.000 |
| 18 | 0.900 |

## Best texts against the seed

### instruction:leader

```diff
(unchanged)
```

### turn_reminder:leader

```diff
--- seed
+++ best
@@ -1 +1 @@
-[Delegation — a question that needs evidence from the machine beyond one quick lookup (several files, logs, a remote host, a cause to establish) goes to the 'investigator' sub-agent first, not to your own Bash, Read, Grep or Glob; a single quick lookup you may do yourself. Two independent questions = two 'investigator' calls in the same response. If the investigator's answer is empty or off-topic, re-task it once with different guidance and no more. Always end with a written answer to the user, saying what is unverified.]+[Delegation — a question needing evidence from the machine beyond one quick lookup (several files, logs, a remote host, a cause to establish) goes to the 'investigator' sub-agent first, not to your own Bash, Read, Grep or Glob; a single quick lookup you may do yourself. One 'investigator' call per independent question, never bundled; the same question about several hosts is several questions, one call per host. Issue all calls in the same response. If an answer is empty or off-topic, re-task that investigator once with different guidance, no more. Always end with a written answer to the user, saying what is unverified.]
```

## Patch

Apply by hand after review (never automatic):

```diff
--- a/registry/agents/leader/agent.json
+++ b/registry/agents/leader/agent.json
@@ -28,5 +28,5 @@
     "spawn",
     "session_history"
   ],
-  "turn_reminder": "[Delegation — a question that needs evidence from the machine beyond one quick lookup (several files, logs, a remote host, a cause to establish) goes to the 'investigator' sub-agent first, not to your own Bash, Read, Grep or Glob; a single quick lookup you may do yourself. Two independent questions = two 'investigator' calls in the same response. If the investigator's answer is empty or off-topic, re-task it once with different guidance and no more. Always end with a written answer to the user, saying what is unverified.]"
+  "turn_reminder": "[Delegation — a question needing evidence from the machine beyond one quick lookup (several files, logs, a remote host, a cause to establish) goes to the 'investigator' sub-agent first, not to your own Bash, Read, Grep or Glob; a single quick lookup you may do yourself. One 'investigator' call per independent question, never bundled; the same question about several hosts is several questions, one call per host. Issue all calls in the same response. If an answer is empty or off-topic, re-task that investigator once with different guidance, no more. Always end with a written answer to the user, saying what is unverified.]"
 }
```
