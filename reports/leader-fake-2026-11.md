# System leader vs scripted investigator — first run (2026-11-22)

The System squad's sub-agents answered from a script (`squad-bench/fake_subagents.py`);
only the leader ran on a real model. Four scenarios, three samples each, leader
on `balanced` then on `premium` (Sonnet 5.5). omnis `develop` at `db28817`.
Records: `leader-fake-2026-11-balanced.jsonl`, `leader-fake-2026-11-premium.jsonl`.
How to run: `squad-bench/README-leader-fake.md`.

Total cost: **$0.55** (balanced $0.22, premium $0.33). Three samples per cell:
read the counts as indications, not rates.

## Results

| Scenario | Leader | Delegated | Investigator calls | Own tool calls | Answer |
|---|---|---|---|---|---|
| `lf-good` (correct finding) | balanced | 0/3 | 0 | 6, 29, 13 | "the logs do not exist" (3/3) |
| | premium | 3/3 | 1, 1, 1 | 0, 4, 4 | finding given (1/3); finding reported as unverified (2/3) |
| `lf-fanout` (two questions) | balanced | 0/3 | 0 | 6, 4, 8 | "the logs do not exist" (3/3) |
| | premium | 3/3 | 2, 2, 2 — in parallel 3/3 | 0, 0, 0 | both findings (3/3) |
| `lf-empty` (never any evidence) | balanced | 0/3 | 0 | 5, 5, 7 | "the logs do not exist" (3/3) |
| | premium | 3/3 | 1, 1, 1 | 2, 1, 1 | "the logs do not exist", no cause stated (3/3) |
| `lf-reword` (off-topic, then the finding for a new request) | balanced | 0/3 | 0 | 3, 3, 9 | "the logs do not exist" (3/3) |
| | premium | 2/3 | 0, 2, 2 | 3, 3, 3 | finding obtained, then rejected as unverifiable (2/3) |

## What it shows

1. **On `balanced` the leader never delegates: 0 of 12 runs.** It investigates
   with its own `Bash` every time, although its instruction says "DELEGATE BY
   DEFAULT … no bash, file edits or MCP calls of your own". In the probe, told
   explicitly to delegate and not use its own tools, it delegated once and then
   made 17 tool calls of its own. For the System squad on `balanced`, the
   members are unused and "delegate by default" is not followed.

2. **On `premium` the leader delegates (11 of 12) and fans out.** Two unrelated
   questions gave two investigator calls in the same response, 3 of 3.

3. **Neither of the two conflicting rules was exercised as written.** The
   leader's instruction says to re-task a failing sub-agent with different
   guidance; the shared block says to stop after two unhelpful attempts.
   - On "No evidence found" (`lf-empty`), premium made **one** call, then checked
     the host itself with 1-2 `Bash` calls and stopped. It did not re-task, and
     it took over at once — which its instruction tells it not to do.
   - On an off-topic answer (`lf-reword`), premium re-tasked with genuinely
     different guidance in both runs where it delegated: the second request
     names the failure of the first ("uptime and disk usage did not address the
     task") and gives exact commands. No repeated or near-repeated request in
     any of the 24 runs.
   So: an empty answer leads to self-checking, an off-topic answer leads to a
   real re-task. The "stop after two attempts" rule never came into play.

4. **The premium leader checks its sub-agent's claims and disowns what it
   cannot reproduce.** In 4 of the 5 runs where the scripted finding cited a
   file, the leader looked for that file, did not find it, and told the user the
   finding was unverified ("I couldn't reproduce that file… don't rely on it").
   This is good behaviour, and it is the main limit of this first bench (below).

5. **Slow runs are the leader's own searches.** Premium runs of 130-200 s
   contain a filesystem-wide search that timed out; the investigator answers in
   0.3 s.

## Limits of this run

- **The scripted evidence contradicts the host.** The findings cite files under
  `/var/log/…` that do not exist, and the leader holds `Bash`. A careful leader
  therefore refutes the script. `lf-good` and `lf-reword` no longer measure "uses
  the finding"; they measure "trusts or checks the sub-agent".
- **`quality_gate` is not reliable here.** It passed two answers that quote the
  finding while disowning it (`lf-good` s2, `lf-reword` s3) and failed one that
  rejected it for a good reason (`lf-reword` s2). Use the table above, which was
  built from the call logs and a reading of the 24 answers.
- **`fake_gate` did its job** for delegation, fan-out and repeats; it failed all
  12 balanced runs for the right reason (no call).
- Three samples per cell, one squad, two models.
- The cost shown for a faked agent is not zero (one token at a non-zero price):
  the zero price of the fake model entries is not what omnis reports. Negligible.

## What to do next

- **Scenario fix (bench).** Make the evidence unreachable for the leader rather
  than absent from the host: either an overlay that removes the leader's own
  tools, or questions about something only the investigator can reach. Then
  `lf-good` / `lf-reword` measure what they were written for.
- **Product question (omnis).** On `balanced`, the System leader ignores its
  members. Either the instruction needs to be made effective on that tier, or
  the System squad on a cheap leader should be a single agent — the same
  conclusion the 2026-11-07 squad-shape work reached for Knowledge.
- **Product question (omnis).** The leader's "do not take over at once" rule is
  not followed even on `premium`, and the result (check it yourself, say what is
  unverified) looks better than the rule. The rule may be the thing to change.
