#!/usr/bin/env bash
# One-role model sweep: ONE omnis-server where a research sub-agent (web_agent or
# web_fetcher) is cloned once per candidate model, each clone behind its own
# Balanced relay squad. Every other role stays on the shipped config, so a cost
# or quality gap is the candidate model's alone. Costs cents per run.
#
# Usage: setup-role.sh <workdir> <role> <port> <ref,ref,...>|stop
#   role  web_agent | web_fetcher | knowledge_leader
# knowledge_leader: each clone leads a full copy of the Knowledge squad (same
# members, no relay) and runs tasks-modelcost.json's TASK_IDS (default
# mc-netbird,mc-kserve). WEB_AGENT=<ref> moves the shared web_agent to that
# model (it keeps its name, which the leader's instruction relies on), so a
# leader x web_agent combination needs one server per web_agent model.
#   refs  model refs from MODELS below (or shipped refs: balanced, hosted, ...)
# Writes <workdir>/tasks-<ref>.json: tasks-callvolume.json's tasks for that role,
# retargeted at the clone's squad `rb-<ref>`. Run them with bench.py --tasks.
#
# SEARCH=ddg runs web search on DuckDuckGo instead of Serper (no key needed).
# Routing is off: the relay must not hand a question back to the Omnis router
# (a run once ended up in the full Knowledge squad that way).
# Needs OPENAI_BASE_URL/OPENAI_API_KEY/SERPER_KEY. OMNIS_SRC = omnis checkout
# (default ../../omnis): its registry/ is used, the binary is built from it.
set -euo pipefail
WORK=${1:?workdir}; ROLE=${2:?role}; PORT=${3:?port}; REFS=${4:?refs or stop}
HERE=$(cd "$(dirname "$0")" && pwd)
OMNIS_SRC=${OMNIS_SRC:-$(cd "$HERE/../../omnis" && pwd)}
home=$WORK/home-$ROLE
if [[ $REFS == stop ]]; then
  [[ -f $home/pid ]] && kill "$(cat "$home/pid")" 2>/dev/null || true; exit 0
fi
taskfile=$HERE/tasks-callvolume.json
case $ROLE in web_agent) tasks=cv-agent ;; web_fetcher) tasks=cv-fetch ;;
  knowledge_leader) tasks=${TASK_IDS:-mc-netbird,mc-kserve}; taskfile=$HERE/tasks-modelcost.json ;;
  *) echo "role must be web_agent, web_fetcher or knowledge_leader" >&2; exit 2 ;; esac

# Gateway prices (model/info, 2026-11-01), $ per million tokens.
MODELS='{
 "gemini25flash":{"model":"gemini-2.5-flash","context_length":1048576,"input_token_price_per_million":0.315,"output_token_price_per_million":2.625,"cached_input_token_price_per_million":0.03},
 "gpt5mini":     {"model":"gpt-5-mini-sweden","context_length":272000,"input_token_price_per_million":0.294,"output_token_price_per_million":2.31,"cached_input_token_price_per_million":0.025},
 "gpt5nano":     {"model":"gpt-5-nano-sweden","context_length":272000,"input_token_price_per_million":0.063,"output_token_price_per_million":0.462,"cached_input_token_price_per_million":0.005},
 "gpt41mini":    {"model":"gpt-4.1-mini-sweden","context_length":1047576,"input_token_price_per_million":0.42,"output_token_price_per_million":1.68,"cached_input_token_price_per_million":0.1},
 "gpt41nano":    {"model":"gpt-4.1-nano-sweden","context_length":1047576,"input_token_price_per_million":0.105,"output_token_price_per_million":0.42,"cached_input_token_price_per_million":0.025},
 "mistralsmall": {"model":"Mistral-Small-3.2-24B-Instruct-ovh","context_length":128000,"input_token_price_per_million":0.094,"output_token_price_per_million":0.294},
 "gptoss120b":   {"model":"gpt-oss-120b-ovh","context_length":128000,"input_token_price_per_million":0.084,"output_token_price_per_million":0.42},
 "dsv4flash":    {"model":"deepseek-v4-flash-scaleway","context_length":229376,"input_token_price_per_million":0.42,"output_token_price_per_million":0.84,"cached_input_token_price_per_million":0.084},
 "dsv41flash":   {"model":"deepseek-v4.1-flash-scaleway","context_length":229376,"input_token_price_per_million":0.63,"output_token_price_per_million":1.89,"cached_input_token_price_per_million":0.126},
 "sonnet55":     {"model":"claude-sonnet-5-5","context_length":200000,"input_token_price_per_million":2.1,"output_token_price_per_million":10.5,"cached_input_token_price_per_million":0.21,"cache_creation_token_price_per_million":2.625},
 "gpt56luna":    {"model":"gpt-5.6-luna","context_length":1050000,"input_token_price_per_million":1.05,"output_token_price_per_million":6.3,"cached_input_token_price_per_million":0.1},
 "glm53":        {"model":"glm-5.3-scaleway","context_length":256000,"input_token_price_per_million":1.89,"output_token_price_per_million":5.775},
 "qwen38":       {"model":"qwen3.8-27b-scaleway","context_length":229376,"input_token_price_per_million":0.63,"output_token_price_per_million":3.465,"cached_input_token_price_per_million":0.126}
}'

src=$WORK/src; sys=$WORK/sys
if [[ ! -x $src/bin/omnis-server ]]; then
  rm -rf "$src"; git -C "$OMNIS_SRC" worktree prune
  git -C "$OMNIS_SRC" worktree add --detach "$src" HEAD >&2
  (cd "$src" && go build -o bin/omnis-server ./server) >&2
fi
if [[ ! -d $sys ]]; then
  cp -r /etc/omnis "$sys"; rm -rf "$sys/registry" "$sys/softskills"
  cp -r "$src/registry" "$src/softskills" "$sys/"
fi

mkdir -p "$home/registry/agents/probe_leader"
cat > "$home/registry/agents/probe_leader/agent.json" <<'J'
{"name":"probe_leader","description":"Bench-only relay leader.","leader":true,"model_ref":"balanced","tools":[],"max_tool_calls":1}
J
cat > "$home/registry/agents/probe_leader/instruction.md" <<'J'
You are a relay used by a benchmark. The user message starts with the name of
the research agent (`web_agent:` or `web_fetcher:`); you have exactly one
research agent. Call it exactly once, passing the rest of the message unchanged
as its request. Then reply with its answer unchanged. Never call it a second
time, never answer yourself, never ask the user anything.
J
echo '{"permissions":{"defaultMode":"bypassPermissions","allow":[],"ask":[],"deny":[]}}' > "$home/permissions.json"
# web_fetcher ships on Hosted, which saturates under parallel load: move it.
mkdir -p "$home/registry/agents/web_fetcher"
[[ $ROLE == web_fetcher ]] || echo '{"model_ref":"balanced"}' > "$home/registry/agents/web_fetcher/agent.json"
if [[ -n ${WEB_AGENT:-} ]]; then
  mkdir -p "$home/registry/agents/web_agent"
  echo "{\"model_ref\":\"$WEB_AGENT\"}" > "$home/registry/agents/web_agent/agent.json"
fi

python3 - "$home" "$sys" "$ROLE" "$REFS" "$MODELS" "$taskfile" "$WORK" "$tasks" <<'PY'
import json, os, shutil, sys
home, sysdir, role, refs, models, tasksf, work, tprefix = sys.argv[1:]
models = json.loads(models); refs = refs.split(",")
cat = {}
for r in refs + [os.environ.get("WEB_AGENT", "")]:
    if r in models:
        cat[r] = dict(models[r], provider_ref="openai-compat")
json.dump({"models": cat}, open(f"{home}/models.json", "w"), indent=1)
base = f"{sysdir}/registry/agents/{role}"
agents, squads = ["probe_leader"], []
for r in refs:
    name = f"{role}_{r}".replace("-", "_")
    d = f"{home}/registry/agents/{name}"
    shutil.rmtree(d, ignore_errors=True); shutil.copytree(base, d)
    a = json.load(open(f"{d}/agent.json")); a.update(name=name, model_ref=r, builtin=False)
    json.dump(a, open(f"{d}/agent.json", "w"), indent=1)
    agents.append(name)
    if role == "knowledge_leader":
        a["leader"] = True; json.dump(a, open(f"{d}/agent.json", "w"), indent=1)
        k = next(q for q in json.load(open(f"{sysdir}/agents.json"))["squads"] if q["name"].lower() == "knowledge")
        squads.append({"name": f"rb-{r}", "description": "role bench", "leader": name, "members": k["members"]})
    else:
        squads.append({"name": f"rb-{r}", "description": "role bench", "leader": "probe_leader", "members": [name]})
cfg = {"agents": agents, "squads": squads}
if os.environ.get("SEARCH", "serper") == "serper":
    cfg["serper_key"] = "SERPER_KEY"
json.dump(cfg, open(f"{home}/agents.json", "w"))
ids = tprefix.split(",")
tasks = [t for t in json.load(open(tasksf))["tasks"] if t["id"] in ids or (len(ids) == 1 and t["id"].startswith(tprefix))]
for r in refs:
    out = [dict(t, squad=f"rb-{r}") for t in tasks]
    json.dump({"tasks": out}, open(f"{work}/tasks-{r}.json", "w"), indent=1)
print("clones:", ", ".join(agents[1:]))
PY

[[ -f $home/pid ]] && kill "$(cat "$home/pid")" 2>/dev/null && sleep 1 || true
[[ ${SEARCH:-serper} == ddg ]] && unset SERPER_KEY
OMNIS_HOME=$home OMNIS_SERVER_ADDR=127.0.0.1:$PORT OMNIS_SERVER_TOKEN=bench OMNIS_ROUTER_SQUAD=none \
OMNIS_UPDATE_CHECK=false OMNIS_NON_INTERACTIVE=1 OMNIS_TURN_MAX_TOKENS=0 OMNIS_TURN_MAX_TOOL_CALLS=0 \
OMNIS_CONFIG_DIRS=$home:$sys OMNIS_SYSTEM_CONFIG_DIR=$sys \
  nohup "$src/bin/omnis-server" --no-browser > "$home/server.log" 2>&1 &
echo $! > "$home/pid"
echo "[$ROLE] port $PORT pid $(cat "$home/pid")"
