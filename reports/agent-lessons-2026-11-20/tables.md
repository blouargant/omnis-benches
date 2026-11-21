| Arm | Run | Tool errors | Tool calls | Hints delivered | Cost | Wall | Correct |
|---|---|---|---|---|---|---|---|
| off | 1 | 3 | 39 | 0 | $0.101 | 54 s | 6/6 |
| off | 2 | 4 | 39 | 0 | $0.088 | 38 s | 6/6 |
| on | 1 | 5 | 33 | 1 | $0.092 | 48 s | 6/6 |
| on | 2 | 4 | 38 | 4 | $0.108 | 64 s | 6/6 |
| on | 3 | 3 | 34 | 2 | $0.105 | 58 s | 6/6 |

| Task | off 1 | off 2 | on 1 | on 2 | on 3 |
|---|---|---|---|---|---|
| lsp-diag-timeout | 0 / 5 | 1 / 7 Edit | 1 / 7 Edit | 1 / 7 Edit (hinted) | 1 / 10 todo_write |
| lsp-diag-worker | 0 / 6 | 0 / 7 | 1 / 6 lsp_diagnostics | 1 / 4 lsp_diagnostics (hinted) | 0 / 5 |
| lsp-diag-svc | 0 / 5 | 0 / 6 | 0 / 5 | 0 / 5 | 0 / 7 |
| lsp-diag-limiter | 1 / 11 Read | 1 / 10 Read | 1 / 5 lsp_diagnostics (hinted) | 0 / 9 | 0 / 4 |
| read-missing-limiter | 1 / 5 Bash | 1 / 4 Read | 1 / 5 Bash | 1 / 4 Read (hinted) | 1 / 4 Read (hinted) |
| read-missing-svc | 1 / 7 Read | 1 / 5 Read | 1 / 5 Read | 1 / 9 Read (hinted) | 1 / 4 Read (hinted) |

re-scored 30 records; correct changed on 0:
