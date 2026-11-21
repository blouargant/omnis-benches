Sessions kept / excluded as infrastructure failures: off 125 / 0, on (cd fix) 125 / 0

### Trap tasks, exposures 2-5 — mean per session

| Metric | off | on (cd fix) |
|---|---|---|
| Trap hits | 0.74 | 0.68 (-8 %, p=0.12) |
| Tool calls | 3.61 | 3.64 (+1 %, p=0.89) |
| Model calls | 4.54 | 4.60 (+1 %, p=0.58) |
| Prompt tokens | 62,079 | 62,382 (+0 %, p=0.67) |
| Cost $ | 0.0239 | 0.0249 (+4 %, p=0.36) |
| Wall s | 8.80 | 8.84 (+0 %, p=0.78) |
| Correct | 80/80 | 80/80 |
| Repetitions | 5 | 5 |

### Opaque traps, exposures 2-5 — mean per session

| Metric | off | on (cd fix) |
|---|---|---|
| Trap hits | 1.00 | 0.95 (-5 %, p=0.45) |
| Tool calls | 4.25 | 4.08 (-4 %, p=0.15) |
| Model calls | 5.17 | 5.05 (-2 %, p=0.25) |
| Prompt tokens | 69,953 | 67,029 (-4 %, p=0.14) |
| Cost $ | 0.0281 | 0.0287 (+2 %, p=0.55) |
| Wall s | 9.50 | 9.07 (-5 %, p=0.21) |
| Correct | 40/40 | 40/40 |
| Repetitions | 5 | 5 |

### Explicit traps, exposures 2-5 — mean per session

| Metric | off | on (cd fix) |
|---|---|---|
| Trap hits | 0.47 | 0.40 (-16 %, p=0.48) |
| Tool calls | 2.98 | 3.20 (+8 %, p=0.11) |
| Model calls | 3.90 | 4.15 (+6 %, p=0.09) |
| Prompt tokens | 54,205 | 57,735 (+7 %, p=0.09) |
| Cost $ | 0.0197 | 0.0210 (+6 %, p=0.25) |
| Wall s | 8.11 | 8.61 (+6 %, p=0.16) |
| Correct | 40/40 | 40/40 |
| Repetitions | 5 | 5 |

### Trap tasks, exposure 1 (no lesson can exist: should not differ) — mean per session

| Metric | off | on (cd fix) |
|---|---|---|
| Trap hits | 1.25 | 1.25 (+0 %, p=1.00) |
| Tool calls | 3.50 | 3.45 (-1 %, p=1.00) |
| Model calls | 4.50 | 4.40 (-2 %, p=0.64) |
| Prompt tokens | 43,145 | 42,898 (-1 %, p=0.90) |
| Cost $ | 0.0397 | 0.0383 (-4 %, p=0.38) |
| Wall s | 5.90 | 5.65 (-4 %, p=0.08) |
| Correct | 20/20 | 20/20 |
| Repetitions | 5 | 5 |

### Control tasks (no trap), all exposures — mean per session

| Metric | off | on (cd fix) |
|---|---|---|
| Trap hits | 0.00 | 0.00 |
| Tool calls | 1.40 | 1.40 (+0 %, p=1.00) |
| Model calls | 2.40 | 2.40 (+0 %, p=1.00) |
| Prompt tokens | 22,980 | 24,002 (+4 %, p=0.52) |
| Cost $ | 0.0189 | 0.0180 (-5 %, p=0.56) |
| Wall s | 2.65 | 2.86 (+8 %, p=0.42) |
| Correct | 25/25 | 25/25 |
| Repetitions | 5 | 5 |

### All 25 sessions — mean per session

| Metric | off | on (cd fix) |
|---|---|---|
| Trap hits | 0.67 | 0.63 (-6 %, p=0.12) |
| Tool calls | 3.15 | 3.16 (+0 %, p=1.00) |
| Model calls | 4.10 | 4.13 (+1 %, p=0.73) |
| Prompt tokens | 51,230 | 51,588 (+1 %, p=0.52) |
| Cost $ | 0.0254 | 0.0256 (+1 %, p=0.76) |
| Wall s | 7.11 | 7.13 (+0 %, p=0.72) |
| Correct | 125/125 | 125/125 |
| Repetitions | 5 | 5 |

### Trap tasks by exposure — mean per session

| Exposure | Condition | Trap hits | Hints | Tool calls | Cost $ | Lessons in prompt at session end |
|---|---|---|---|---|---|---|
| 1 | off | 1.25 | 0.00 | 3.50 | 0.0397 | 0.0 |
| 1 | on (cd fix) | 1.25 | 0.00 | 3.45 | 0.0383 | 0.0 |
| 2 | off | 0.95 | 0.00 | 3.55 | 0.0259 | 0.0 |
| 2 | on (cd fix) | 0.80 | 0.00 | 3.65 | 0.0257 | 0.0 |
| 3 | off | 0.75 | 0.00 | 3.10 | 0.0224 | 0.0 |
| 3 | on (cd fix) | 0.75 | 0.00 | 3.35 | 0.0263 | 0.0 |
| 4 | off | 1.00 | 0.00 | 3.80 | 0.0214 | 0.0 |
| 4 | on (cd fix) | 1.00 | 0.00 | 3.70 | 0.0229 | 0.0 |
| 5 | off | 0.25 | 0.00 | 4.00 | 0.0259 | 0.0 |
| 5 | on (cd fix) | 0.15 | 0.00 | 3.85 | 0.0245 | 0.0 |
