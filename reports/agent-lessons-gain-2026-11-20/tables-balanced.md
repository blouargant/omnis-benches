Sessions kept / excluded as infrastructure failures: off 232 / 18, on (as merged) 121 / 4, on (cd fix) 113 / 12

### Trap tasks, exposures 2-5 — mean per session

| Metric | off | on (as merged) | on (cd fix) |
|---|---|---|---|
| Trap hits | 0.68 | 0.62 (-8 %, p=0.50) | 0.61 (-9 %, p=0.37) |
| Tool calls | 7.32 | 6.93 (-5 %, p=0.44) | 6.74 (-8 %, p=0.14) |
| Model calls | 6.92 | 6.52 (-6 %, p=0.28) | 6.48 (-6 %, p=0.16) |
| Prompt tokens | 68,117 | 65,395 (-4 %, p=0.43) | 64,850 (-5 %, p=0.26) |
| Cost $ | 0.0188 | 0.0181 (-4 %, p=0.44) | 0.0180 (-5 %, p=0.26) |
| Wall s | 17.25 | 15.65 (-9 %, p=0.06) | 16.93 (-2 %, p=0.67) |
| Correct | 151/154 | 77/78 | 71/73 |
| Repetitions | 10 | 5 | 5 |

### Opaque traps, exposures 2-5 — mean per session

| Metric | off | on (as merged) | on (cd fix) |
|---|---|---|---|
| Trap hits | 0.91 | 0.90 (-1 %, p=0.96) | 0.95 (+4 %, p=0.81) |
| Tool calls | 7.26 | 7.08 (-3 %, p=0.76) | 6.87 (-5 %, p=0.51) |
| Model calls | 7.15 | 6.88 (-4 %, p=0.57) | 6.90 (-3 %, p=0.58) |
| Prompt tokens | 71,126 | 69,740 (-2 %, p=0.77) | 70,930 (-0 %, p=0.97) |
| Cost $ | 0.0196 | 0.0193 (-2 %, p=0.79) | 0.0196 (-0 %, p=0.97) |
| Wall s | 17.42 | 16.87 (-3 %, p=0.64) | 18.43 (+6 %, p=0.40) |
| Correct | 76/78 | 39/40 | 35/35 |
| Repetitions | 10 | 5 | 5 |

### Explicit traps, exposures 2-5 — mean per session

| Metric | off | on (as merged) | on (cd fix) |
|---|---|---|---|
| Trap hits | 0.44 | 0.34 (-24 %, p=0.27) | 0.31 (-29 %, p=0.22) |
| Tool calls | 7.41 | 6.77 (-9 %, p=0.39) | 6.58 (-11 %, p=0.23) |
| Model calls | 6.69 | 6.14 (-8 %, p=0.21) | 6.07 (-9 %, p=0.19) |
| Prompt tokens | 65,094 | 60,764 (-7 %, p=0.27) | 58,884 (-10 %, p=0.15) |
| Cost $ | 0.0181 | 0.0169 (-7 %, p=0.28) | 0.0164 (-9 %, p=0.17) |
| Wall s | 17.08 | 14.35 (-16 %, p=0.13) | 15.48 (-9 %, p=0.45) |
| Correct | 75/76 | 38/38 | 36/38 |
| Repetitions | 10 | 5 | 5 |

### Trap tasks, exposure 1 (no lesson can exist: should not differ) — mean per session

| Metric | off | on (as merged) | on (cd fix) |
|---|---|---|---|
| Trap hits | 0.86 | 0.75 (-13 %, p=0.38) | 0.93 (+9 %, p=0.62) |
| Tool calls | 3.58 | 3.35 (-6 %, p=0.61) | 3.63 (+2 %, p=0.92) |
| Model calls | 4.27 | 4.20 (-2 %, p=0.86) | 4.18 (-2 %, p=0.83) |
| Prompt tokens | 38,829 | 37,349 (-4 %, p=0.53) | 37,935 (-2 %, p=0.75) |
| Cost $ | 0.0105 | 0.0101 (-4 %, p=0.48) | 0.0103 (-2 %, p=0.73) |
| Wall s | 6.15 | 6.32 (+3 %, p=0.75) | 5.62 (-9 %, p=0.18) |
| Correct | 36/36 | 20/20 | 17/17 |
| Repetitions | 10 | 5 | 5 |

### Control tasks (no trap), all exposures — mean per session

| Metric | off | on (as merged) | on (cd fix) |
|---|---|---|---|
| Trap hits | 0.00 | 0.00 | 0.00 |
| Tool calls | 1.85 | 2.53 (+37 %, p=0.16) | 1.65 (-11 %, p=0.61) |
| Model calls | 2.81 | 3.20 (+14 %, p=0.34) | 2.61 (-7 %, p=0.60) |
| Prompt tokens | 23,567 | 29,734 (+26 %, p=0.21) | 24,290 (+3 %, p=0.86) |
| Cost $ | 0.0065 | 0.0082 (+27 %, p=0.21) | 0.0067 (+3 %, p=0.85) |
| Wall s | 4.63 | 7.02 (+52 %, p=0.13) | 4.88 (+6 %, p=0.83) |
| Correct | 42/42 | 23/23 | 23/23 |
| Repetitions | 10 | 5 | 5 |

### All 25 sessions — mean per session

| Metric | off | on (as merged) | on (cd fix) |
|---|---|---|---|
| Trap hits | 0.58 | 0.53 (-10 %, p=0.26) | 0.54 (-8 %, p=0.36) |
| Tool calls | 5.76 | 5.52 (-4 %, p=0.43) | 5.26 (-9 %, p=0.13) |
| Model calls | 5.77 | 5.51 (-4 %, p=0.27) | 5.37 (-7 %, p=0.10) |
| Prompt tokens | 55,532 | 54,057 (-3 %, p=0.49) | 52,765 (-5 %, p=0.18) |
| Cost $ | 0.0153 | 0.0149 (-3 %, p=0.49) | 0.0146 (-5 %, p=0.19) |
| Wall s | 13.25 | 12.50 (-6 %, p=0.25) | 12.83 (-3 %, p=0.48) |
| Correct | 229/232 | 120/121 | 111/113 |
| Repetitions | 10 | 5 | 5 |

### Trap tasks by exposure — mean per session

| Exposure | Condition | Trap hits | Hints | Tool calls | Cost $ | Lessons in prompt at session end |
|---|---|---|---|---|---|---|
| 1 | off | 0.86 | 0.00 | 3.58 | 0.0105 | 0.0 |
| 1 | on (as merged) | 0.75 | 0.00 | 3.35 | 0.0101 | 0.0 |
| 1 | on (cd fix) | 0.94 | 0.00 | 3.65 | 0.0104 | 0.0 |
| 2 | off | 0.68 | 0.00 | 6.18 | 0.0160 | 0.0 |
| 2 | on (as merged) | 0.65 | 0.45 | 6.20 | 0.0171 | 0.0 |
| 2 | on (cd fix) | 0.44 | 0.56 | 8.06 | 0.0194 | 0.2 |
| 3 | off | 0.53 | 0.00 | 9.10 | 0.0213 | 0.0 |
| 3 | on (as merged) | 0.60 | 0.45 | 8.90 | 0.0215 | 0.6 |
| 3 | on (cd fix) | 0.58 | 0.53 | 7.32 | 0.0183 | 0.9 |
| 4 | off | 0.72 | 0.00 | 7.33 | 0.0194 | 0.0 |
| 4 | on (as merged) | 0.44 | 0.39 | 6.94 | 0.0167 | 1.1 |
| 4 | on (cd fix) | 0.79 | 0.74 | 5.89 | 0.0165 | 1.9 |
| 5 | off | 0.78 | 0.00 | 6.59 | 0.0185 | 0.0 |
| 5 | on (as merged) | 0.80 | 0.45 | 5.80 | 0.0173 | 1.9 |
| 5 | on (cd fix) | 0.65 | 0.41 | 5.71 | 0.0178 | 2.6 |
