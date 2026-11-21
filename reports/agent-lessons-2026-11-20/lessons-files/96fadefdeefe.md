---
id: 96fadefdeefe
agent: coder
tool: todo_write
signature: 96fadefdeefec77997c0d4afa41387177886df2fde981597ffe8b7da78693088
state: hint
created: 2026-11-20T21:04:27.861780428Z
last_seen: 2026-11-20T21:04:27.861780428Z
seen: 1
hinted: 0
recovered: 0
repeated: 0
seen_in_prompt: 0
sessions: selected-wasp
---

Cue: todo_write expects tasks as a list of strings, not objects
Text: When calling todo_write, ensure the "tasks" argument is a JSON array of strings, not an array of objects containing content and status fields.

Failed:
```
validating root: validating /properties/tasks: validating /properties/tasks/items: type: map[content:Read handlers.go and locate handleUpload timeout status:in_progress] has type "object", want "string"
```

Worked:
```
{"tasks":["Read handlers.go and locate handleUpload timeout","Raise handleUpload timeout from 5s to 30s, leave handleDownload unchanged","Run lsp_diagnostics on handlers.go and verify clean"]}
```
