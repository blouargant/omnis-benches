# Squad shape under production tiering (2026-11-07)

Design: `omnis/docs/superpowers/specs/2026-11-07-squad-shape-design.md`;
plan: `omnis/docs/superpowers/plans/2026-11-07-squad-shape.md`.
Budget 50 € (58 $ at 1 € = 1.16 $); spend in `squad-shape-ledger.jsonl`.

## Gateway check

`claude-sonnet-5-5` (premium), no `max_tokens`, 1,500-word essay: `finish_reason:
stop` at **5,128** completion tokens — the 4,096 cap reported on 2026-10-31 is
gone; no `max_output_tokens` override needed.
