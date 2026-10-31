#!/usr/bin/env bash
# Start one isolated omnis-server per model variant (own OMNIS_HOME, own port).
# Usage: setup-modelcost.sh <workdir> start|stop [V0,V1,...]
# Needs OPENAI_BASE_URL/OPENAI_API_KEY/SERPER_KEY in the environment.
#
# A variant may name an omnis git ref as a 4th field: the script then builds
# omnis-server from that ref (worktree under <workdir>/src-*) and runs it on a
# copy of /etc/omnis whose registry/ and softskills/ come from that ref. That
# compares two omnis versions (prompts + code) on otherwise identical config.
# OMNIS_SRC points at the omnis checkout (default ../omnis).
set -euo pipefail
WORK=${1:?workdir}; CMD=${2:-start}; ONLY=${3:-}
declare -A V=(
  [V0]="premium balanced high"          # shipped baseline
  [V1]="sonnet55 balanced high"         # leader -> Claude Sonnet 5.5
  [V2]="deepseek41 balanced high"       # leader -> DeepSeek v4.1 flash
  [V3]="premium deepseek41 high"        # web_agent -> DeepSeek v4.1 flash
  [V4]="premium hosted high"            # web_agent -> Hosted (Qwen3.6-27B self-hosted)
  [V5]="deepseek41 deepseek41 deepseek41" # leader + web_agent + critic -> DeepSeek
  [V6]="sonnet55 hosted deepseek41"     # cheapest-plausible mix
  [V7]="qwen38 balanced high"           # leader -> Qwen3.8-27B (Scaleway, cached)
  [V8]="premium qwen38 high"            # web_agent -> Qwen3.8-27B
  [W0]="premium balanced high develop"                    # omnis develop
  [W1]="premium balanced high perf/knowledge-call-volume" # call-volume bounds
)
OMNIS_SRC=${OMNIS_SRC:-$(cd "$(dirname "$0")/../../omnis" && pwd)}

# build_ref <ref> → echoes "<binary> <system-config-dir>" for that omnis ref.
build_ref() {
  local ref=$1 slug=${1//\//_}
  local src=$WORK/src-$slug sys=$WORK/sys-$slug
  if [[ ! -x $src/bin/omnis-server ]]; then
    rm -rf "$src"; git -C "$OMNIS_SRC" worktree prune
    git -C "$OMNIS_SRC" worktree add --detach "$src" "$ref" >&2
    (cd "$src" && go build -o bin/omnis-server ./server) >&2
  fi
  if [[ ! -d $sys ]]; then
    cp -r /etc/omnis "$sys"
    rm -rf "$sys/registry" "$sys/softskills"
    cp -r "$src/registry" "$src/softskills" "$sys/"
  fi
  echo "$src/bin/omnis-server $sys"
}
PORT0=8190
i=0
for v in $(printf '%s\n' "${!V[@]}" | sort); do
  port=$((PORT0+i)); i=$((i+1)); home=$WORK/$v
  [[ -n $ONLY && ,$ONLY, != *,$v,* ]] && continue
  if [[ $CMD == stop ]]; then
    [[ -f $home/pid ]] && kill "$(cat $home/pid)" 2>/dev/null || true; continue
  fi
  read -r leader web critic ref <<<"${V[$v]}"
  bin=omnis-server; sys=/etc/omnis
  if [[ -n ${ref:-} ]]; then read -r bin sys < <(build_ref "$ref"); fi
  mkdir -p "$home/registry/agents"/{knowledge_leader,web_agent,research_critic,web_fetcher}
  # web_fetcher ships on Hosted (self-hosted, 2 GPUs): a parallel campaign
  # saturates it (2026-10-30), so every variant moves it to Balanced.
  echo '{"model_ref":"balanced"}' > "$home/registry/agents/web_fetcher/agent.json"
  echo "{\"model_ref\":\"$leader\"}" > "$home/registry/agents/knowledge_leader/agent.json"
  echo "{\"model_ref\":\"$web\"}"    > "$home/registry/agents/web_agent/agent.json"
  echo "{\"model_ref\":\"$critic\"}" > "$home/registry/agents/research_critic/agent.json"
  echo '{"serper_key":"SERPER_KEY"}' > "$home/agents.json"
  # Nobody can click a permission card in a bench: allow everything (the Bash
  # safety floor still applies). Same as k8s-ai-bench/bench-permissions.json.
  echo '{"permissions":{"defaultMode":"bypassPermissions","allow":[],"ask":[],"deny":[]}}' > "$home/permissions.json"
  cat > "$home/models.json" <<'J'
{"models":{
 "sonnet55":  {"provider_ref":"openai-compat","model":"claude-sonnet-5-5","context_length":200000,
               "input_token_price_per_million":2.1,"output_token_price_per_million":10.5,
               "cached_input_token_price_per_million":0.21,"cache_creation_token_price_per_million":2.625},
 "qwen38":    {"provider_ref":"openai-compat","model":"qwen3.8-27b-scaleway","context_length":229376,
               "input_token_price_per_million":0.63,"output_token_price_per_million":3.465,
               "cached_input_token_price_per_million":0.126},
 "deepseek41":{"provider_ref":"openai-compat","model":"deepseek-v4.1-flash-scaleway","context_length":229376,
               "input_token_price_per_million":0.63,"output_token_price_per_million":1.89,
               "cached_input_token_price_per_million":0.126}
}}
J
  echo "[$v] port $port  leader=$leader web_agent=$web critic=$critic ${ref:+omnis=$ref}"
  OMNIS_HOME=$home OMNIS_SERVER_ADDR=127.0.0.1:$port OMNIS_SERVER_TOKEN=bench \
  OMNIS_UPDATE_CHECK=false OMNIS_NON_INTERACTIVE=1 OMNIS_TURN_MAX_TOKENS=0 OMNIS_TURN_MAX_TOOL_CALLS=0 \
  OMNIS_CONFIG_DIRS=$home:$sys OMNIS_SYSTEM_CONFIG_DIR=$sys \
    nohup "$bin" --no-browser > "$home/server.log" 2>&1 &
  echo $! > "$home/pid"
done
