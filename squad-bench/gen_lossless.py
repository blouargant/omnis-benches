#!/usr/bin/env python3
"""Derive a lossless filter set from config/filters.

Rules:
 1. DROP filters for commands whose output IS the answer (queries, listings,
    VCS inspection): no filter => raw output (the 32 KB shaper still caps it).
 2. For every kept filter, delete head/tail/truncate_lines (pure truncation)
    and any inject that changes what the command reports.
 3. keep_lines is kept ONLY for installers (their output is progress noise);
    elsewhere it would drop error context, so it is removed.
 4. Installers matching a whole binary (npm, pip, docker...) are narrowed to
    their install-like subcommands so `npm test` / `pip list` stay raw.
 5. go test / cargo test are hand-written: drop PASS noise, keep every
    failure line, append a pass/fail count.
"""
import json, glob, os, sys, copy
src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
for f in glob.glob(os.path.join(dst, "*.json")): os.remove(f)

DROP = set("""kubectl-get kubectl-logs helm aws gcloud jq psql curl wget ssh sops stat wc du df ls
tree find grep rg diff ps iptables git-branch git-diff git-show git-log git-stash git-worktree
git-status git-commit docker-images docker-ps docker-compose docker-logs pnpm-list gh-issue gh-pr
gh-run jira systemctl fail2ban skopeo ollama rails-routes jj yadm gt just task npx liquibase
spring-boot shopify mise ping rsync go-test cargo-test""".split())
INSTALLERS = {  # filter -> install-like subcommands (None = already scoped)
 "npm-install": ["install", "i", "ci", "update"], "pip-install": ["install", "uninstall"],
 "poetry-install": ["install", "add", "update", "lock"], "uv-sync": ["sync", "add", "lock"],
 "pnpm-install": ["install", "i", "add"], "yarn-install": ["install", "add"],
 "brew-install": ["install", "upgrade", "reinstall"], "composer-install": ["install", "update", "require"],
 "docker-build": ["build"], "bundle-install": None, "cargo-install": None,
}
CUT = {"head", "tail", "truncate_lines"}
kept = dropped = 0
for path in sorted(glob.glob(os.path.join(src, "*.json"))):
    name = os.path.basename(path)[:-5]
    if name in DROP:
        dropped += 1; continue
    d = json.load(open(path))
    inst = name in INSTALLERS
    d["pipeline"] = [s for s in d["pipeline"] if s["action"] not in CUT
                     and (inst or s["action"] != "keep_lines")]
    d.pop("inject", None)
    d["description"] = "[lossless] " + d.get("description", "")
    if not any(s["action"] not in ("strip_ansi", "on_empty") for s in d["pipeline"]) and not inst:
        # nothing left but ANSI stripping: still harmless, keep it
        pass
    subs = INSTALLERS.get(name)
    if subs:
        for sc in subs:
            c = copy.deepcopy(d); c["name"] = f"{name}-{sc}"; c["match"]["subcommand"] = sc
            json.dump(c, open(os.path.join(dst, c["name"] + ".json"), "w"), indent=2); kept += 1
    else:
        json.dump(d, open(os.path.join(dst, name + ".json"), "w"), indent=2); kept += 1

HAND = {
 "go-test": {"name": "go-test", "version": 1,
   "description": "[lossless] go test: drop RUN/PASS noise, keep all failure output, append counts",
   "match": {"command": "go", "subcommand": "test", "exclude_flags": ["-json", "-bench"]},
   "inject": {"args": ["-v"], "skip_if_present": ["-v", "-json", "-bench"]},
   "pipeline": [
     {"action": "aggregate", "append": True,
      "patterns": {"passed": "^--- PASS", "failed": "^--- FAIL"},
      "format": "== top-level tests: {{.passed}} passed, {{.failed}} failed"},
     {"action": "remove_lines", "pattern": "^\\s*(=== (RUN|PAUSE|CONT|NAME)\\b|--- PASS\\b|--- SKIP\\b)|^PASS$"}],
   "on_error": "passthrough"},
 "cargo-test": {"name": "cargo-test", "version": 1,
   "description": "[lossless] cargo test: drop build/pass noise, keep failures, append counts",
   "match": {"command": "cargo", "subcommand": "test"},
   "streams": ["stdout", "stderr"],
   "pipeline": [
     {"action": "aggregate", "append": True,
      "patterns": {"passed": "\\.\\.\\. ok$", "failed": "\\.\\.\\. FAILED$"},
      "format": "== tests: {{.passed}} passed, {{.failed}} failed"},
     {"action": "remove_lines", "pattern": "^\\s*(Compiling|Downloading|Downloaded|Updating|Fresh|Blocking)\\b|\\.\\.\\. ok$|^\\s*$"}],
   "on_error": "passthrough"},
}
for n, d in HAND.items():
    json.dump(d, open(os.path.join(dst, n + ".json"), "w"), indent=2); kept += 1
print(f"kept {kept} filters, dropped {dropped}")
