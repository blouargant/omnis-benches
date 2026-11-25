# Scenarios from real sessions — study report

## Scope

One machine. 50 recorded turns with tool calls, from 2026-10-28 to 2026-11-18. By squad: knowledge 45, system 4, iaparc 1.

## Funnel

| Step | Count |
|---|---|
| Turns scanned | 50 |
| Flagged | 19 |
| Cards reviewed | 27 |
| Confirmed failures | 5 |
| Scenarios | 4 |
| Reproduce | 1 |
| Not covered | 1 |

## Precision of each way of flagging a turn

| Method | Turns flagged | Checked | Real failures | Precision |
|---|---|---|---|---|
| empty_subagent | 1 | 1 | 1 | 100 % |
| halted | 4 | 4 | 2 | 50 % |
| many_calls | 4 | 4 | 3 | 75 % |
| repeated_call | 4 | 4 | 2 | 50 % |
| tool_error | 16 | 16 | 4 | 25 % |
| judge | 8 | 8 | 4 | 50 % |

Turns nobody flagged, drawn at random: 8 checked, 0 were real failures.

## Scenarios

| Id | Squad | Failure looked for | Runs | Failure seen | Passed | Status | Cost |
|---|---|---|---|---|---|---|---|
| ss-1 | knowledge | Déploie une recherche exhaustive disproportionnée (skill deep-research, plusieurs vagues de sous-agents web, un critique, près de 300 appels d'outils, dérive vers des chauffages d'appoint portables) et ouvre la réponse par une narration du processus au lieu de la recommandation. | 5 (0 invalid) | 0 | 0 | does not reproduce | $1.43 |
| ss-2 | knowledge | Le verdict « meilleur modèle ouvert pour le codage » repose surtout sur un seul benchmark ou une seule source (FrontierCode), alors que le plan prévoyait plusieurs benchmarks (SWE-bench Pro, Vals, Terminal-Bench, etc.) qui n'ont pas été croisés avant de conclure. | 5 (1 invalid) | 2 | 1 | reproduces | $5.21 |
| ss-3 | system | La recherche web est déléguée à un sous-agent d'investigation qui enchaîne des dizaines d'appels curl|grep sur des pages rendues en JavaScript (dont un appel à une API avec la clé locale) et renvoie un brief confus, que l'agent principal écarte ensuite, au lieu d'utiliser directement les outils de recherche et de lecture web en une dizaine d'appels. | 5 (0 invalid) | 0 | 4 | does not reproduce | $0.66 |
| ss-4 | knowledge | L'agent enchaîne des centaines d'appels d'outils : recherches qui échouent en boucle avec la même erreur HTTP 400, URL d'API ou de pages devinées qui renvoient 404, délégations qui reviennent vides et sont relancées, et la réponse finale reste incomplète (prix OVHcloud partiels, aucun prix Outscale). | 5 (0 invalid) | 0 | 4 | does not reproduce | $0.78 |
| ss-c1 | knowledge | (control) | 5 (0 invalid) | 0 | 5 | control ok | $0.15 |
| ss-c2 | knowledge | (control) | 5 (0 invalid) | 0 | 4 | control ok | $0.36 |

## Coverage by existing suites

| Id | Group | Covered by |
|---|---|---|
| ss-2 | verdict-on-one-benchmark | none |

## Signals that were missing

- a Stop by the user (not recorded)
- a rewind (it deletes the turns it rewinds)
- tool calls of injected turns (scheduled, mailbox, spawned)
- the files' state at the time of the turn
- the user's judgement of the answer (only visible when the next message pushes back)
- which searches failed for a provider-side reason (Serper HTTP 400) rather than the agent's

## Spend

Replay: $8.58. Turn judge: 372763 tokens.

## Verdict

**undecided** — 1 distinct failure(s) reproduce and are not covered by an existing suite.

Fixed before the study: go on to a failure marker in omnis when 3 or more distinct failures reproduce and no existing suite covers them; stop when none does; 1 or 2 is undecided.

## Limits

- One user, one machine, a few weeks of recorded tool calls, mostly one squad.
- Live web: a scenario's result can change with the web, not only with omnis.
- Stop and rewind, the two clearest signs of an unhappy user, are invisible.
- The same model family may write the scenarios and judge the turns.
- A reproduced failure shows the scenario is a usable test; it does not show that fixing it improves real sessions.

## Notes added by hand

- **Who checked the cards.** The 27 review cards were judged by a Claude model
  (an agent, at the user's request), not by the user. The turn judge is of the
  same family, so the precision table measures agreement between two models of
  one family more than precision against a human. The six scenarios were read
  and accepted by the user.
- **Bench server vs the user's install.** The replay server ran `develop`
  (6a6a901) on the production tiers, but with the turn budget off, permissions
  bypassed and nobody to answer a question. The search provider worked there;
  on the user's install 151 searches returned HTTP 400 (a configuration fault,
  reported separately). ss-4's source failure was mostly the agent working
  around those errors, which explains why it does not reproduce.
- **ss-2, coverage.** `squad-bench/tasks-modelcost.json` asks research questions
  of the same kind and its judge scores "evidence", but no task checks that a
  "best X" verdict crosses several independent measures. Counted as not
  covered. Of 4 valid runs, 1 passed the rubric; a fifth was cancelled at the
  15-minute limit.
- **ss-1, a milder form of the failure.** The failure as written (near 300
  calls, sub-agents, a critic) was seen 0 times, so by the rule it does not
  reproduce. But the rubric failed 5 times out of 5: four runs loaded the
  deep-research skill and made 30 to 38 tool calls for a purchase question,
  opening with an account of the process; one run announced its plan and ended
  the turn without researching. The failure text was written too narrowly
  (copied from the worst session, where the same request took 15 calls twice
  and 129 and 286 calls in two others). Not counted in the verdict, since the
  rule was fixed first; a scenario worded "deep research on a simple purchase
  question" would likely reproduce.
- **ss-3.** In the source session the System leader delegated the web research
  to its investigator; on this checkout it searched directly in all five runs.
- **Signals vs judge.** Of the 5 confirmed failures, the cheap signals found 4
  and the judge found 4; each found one the other missed. The one failure that
  reproduces (ss-2, a verdict resting on one source) was found by the judge
  alone: it is a fault in the answer's quality, which leaves no trace in the
  tool calls. `tool_error` alone is noise (4 real in 16). None of the 8
  unflagged turns was a failure.
