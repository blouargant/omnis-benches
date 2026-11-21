#!/usr/bin/env python3
"""Write squad-bench/tasks-lessons-gain.json: 4 traps x 5 exposures + 5 controls,
ordered round-robin (exposure k of every trap, then control k)."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
SUFFIX = " Work directly, do not delegate. Reply with one short line."
SIDE = [
    "",
    "First add the comment line `# reviewed` as the last line of lib/strings.sh. Then ",
    "First add a function `lower` to lib/strings.sh that lower-cases its argument (same style as `upper`). Then ",
    "First change the README title from `# acme` to `# acme toolkit`. Then ",
    "First add the comment line `# entry point` as the second line of lib/main.sh. Then ",
]
TRAPS = {
    # explicit: the error message says what to do
    "build": dict(kind="explicit", marker="--profile is required", token="ACME-B41K",
                  ask="build the project with the project CLI (`./bin/acme build`, development profile) and tell me the artifact id it prints."),
    "migrate": dict(kind="explicit", marker="no database configured", token="ACME-M77X",
                    ask="run `./scripts/migrate.sh status` against the local dev database and tell me the check id it prints."),
    # opaque: the error is a code, the fix is in docs/
    "test": dict(kind="opaque", marker="FATAL: workspace not initialised", token="ACME-T93D",
                 ask="run the test suite with `make test` and tell me the run id it prints."),
    "notes": dict(kind="opaque", marker="error: E42", token="ACME-R58P",
                  ask="generate the release notes with `./bin/acme release notes` and tell me the notes id it prints."),
}
CONTROLS = [
    ("In lib/strings.sh add a function `lower` that lower-cases its argument, in the same style as `upper`.", {"file": "lib/strings.sh", "match": "/lower\\(\\)/"}),
    ("Tell me which functions lib/strings.sh defines.", {"answer": "/trim_left/"}),
    ("In lib/main.sh, replace the word hello with world.", {"file": "lib/main.sh", "match": "/world/"}),
    ("Tell me what `make lint` prints.", {"answer": "/lint ok/"}),
    ("How many lines does docs/RELEASING.md have? Give the number.", {"answer": "/\\b6\\b/"}),
]
tasks = []
for k in range(5):
    for name, t in TRAPS.items():
        prompt = SIDE[k] + t["ask"] if SIDE[k] else t["ask"][0].upper() + t["ask"][1:]
        prompt += " If a command fails, work out why and get it to succeed."
        tasks.append({"id": f"{name}-{k+1}", "squad": "coding", "fixture": "acme", "kind": "lessons-gain",
                      "trap": name, "trap_kind": t["kind"], "marker": t["marker"], "exposure": k + 1,
                      "cwd": "${GAIN_FIXTURES}/acme", "prompt": prompt + SUFFIX,
                      "check": [{"answer": "/" + t["token"] + "/"}]})
    p, c = CONTROLS[k]
    tasks.append({"id": f"control-{k+1}", "squad": "coding", "fixture": "acme", "kind": "lessons-gain",
                  "trap": "control", "trap_kind": "control", "marker": None, "exposure": k + 1,
                  "cwd": "${GAIN_FIXTURES}/acme", "prompt": p + SUFFIX, "check": [c]})
out = os.path.join(HERE, "..", "..", "squad-bench", "tasks-lessons-gain.json")
json.dump({"tasks": tasks}, open(out, "w"), indent=1)
print(len(tasks), "tasks ->", os.path.normpath(out))
