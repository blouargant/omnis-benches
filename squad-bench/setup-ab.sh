#!/usr/bin/env bash
# A/B two omnis builds on the SAME config: one omnis-server per arm, built from
# a git ref of the omnis checkout (or "worktree" = the uncommitted working
# tree), its own config/ + registry/ as the system layer, and every agent
# forced onto one model (single-model override). Routing stays on.
#
# Usage: setup-ab.sh <workdir> <label> <ref|worktree> <port>   (start)
#        setup-ab.sh <workdir> <label> stop
# Env: MODEL (gateway model id, default deepseek-v4.1-flash-scaleway; "tiered"
#      keeps the shipped model tiers = production), OVERLAY (a squad-shape
#      overlay dir from shape_overlay.py, copied into the arm's user layer),
#      IN/OUT/CACHE prices ($/M), OMNIS_SRC (default ../../omnis).
# Then: bench.py --server http://127.0.0.1:<port> --token bench --tasks tasks-prompt-ab.json --suite
set -euo pipefail
WORK=${1:?workdir}; LABEL=${2:?label}; REF=${3:?ref|worktree|stop}
HERE=$(cd "$(dirname "$0")" && pwd)
OMNIS_SRC=${OMNIS_SRC:-$(cd "$HERE/../../omnis" && pwd)}
arm=$WORK/$LABEL
if [[ $REF == stop ]]; then
  [[ -f $arm/pid ]] && kill "$(cat "$arm/pid")" 2>/dev/null || true; exit 0
fi
PORT=${4:?port}
MODEL=${MODEL:-deepseek-v4.1-flash-scaleway}
mkdir -p "$arm"
if [[ ! -x $arm/src/bin/omnis-server ]]; then
  commit=$REF
  if [[ $REF == worktree ]]; then   # snapshot the working tree without touching the index
    idx=$(mktemp); cp "$OMNIS_SRC/.git/index" "$idx"
    GIT_INDEX_FILE=$idx git -C "$OMNIS_SRC" add -A
    tree=$(GIT_INDEX_FILE=$idx git -C "$OMNIS_SRC" write-tree); rm -f "$idx"
    commit=$(git -C "$OMNIS_SRC" commit-tree "$tree" -p HEAD -m "ab snapshot $LABEL")
  fi
  rm -rf "$arm/src"; git -C "$OMNIS_SRC" worktree prune
  git -C "$OMNIS_SRC" worktree add --detach "$arm/src" "$commit" >&2
  (cd "$arm/src" && go build -o bin/omnis-server ./server) >&2
  echo "$commit" > "$arm/commit"
fi
sys=$arm/sys; home=$arm/home
rm -rf "$sys" "$home"; mkdir -p "$sys" "$home"
cp -r "$arm/src/config/"* "$sys/"; cp -r "$arm/src/registry" "$arm/src/softskills" "$sys/"
python3 - "$sys" "$MODEL" "${IN:-0.63}" "${OUT:-1.89}" "${CACHE:-0.126}" <<'PY'
import json, sys
d, model, i, o, c = sys.argv[1], sys.argv[2], *map(float, sys.argv[3:])
m = json.load(open(f"{d}/models.json"))
if model == "tiered":
    m["override_model_enabled"], m["embed_model_ref"] = False, ""
else:
    m["models"]["abmodel"] = {"provider_ref": "openai-compat", "model": model, "context_length": 229376,
        "input_token_price_per_million": i, "output_token_price_per_million": o, "cached_input_token_price_per_million": c}
    m["override_model_ref"], m["override_model_enabled"], m["embed_model_ref"] = "abmodel", True, ""
json.dump(m, open(f"{d}/models.json", "w"), indent=1)
a = json.load(open(f"{d}/agents.json")); a["serper_key"] = "SERPER_KEY"
json.dump(a, open(f"{d}/agents.json", "w"), indent=1)
PY
echo '{"permissions":{"defaultMode":"bypassPermissions","allow":[],"ask":[],"deny":[]}}' > "$home/permissions.json"
[[ -n ${OVERLAY:-} ]] && cp -r "$OVERLAY"/. "$home/"
[[ -f $arm/pid ]] && kill "$(cat "$arm/pid")" 2>/dev/null && sleep 1 || true
env -u OMNIS_CONFIG_PATH OMNIS_HOME=$home HOME=$home OMNIS_SERVER_ADDR=127.0.0.1:$PORT OMNIS_SERVER_TOKEN=bench \
  OMNIS_UPDATE_CHECK=false OMNIS_NON_INTERACTIVE=1 OMNIS_TURN_MAX_TOKENS=0 OMNIS_TURN_MAX_TOOL_CALLS=0 \
  OMNIS_CONFIG_DIRS=$home:$sys OMNIS_SYSTEM_CONFIG_DIR=$sys OMNIS_AGENTSKILLS_DIR= OMNIS_CURATOR_ENABLED=false \
  nohup "$arm/src/bin/omnis-server" --no-browser > "$arm/server.log" 2>&1 &
echo $! > "$arm/pid"
echo "[$LABEL] $(cat "$arm/commit") port $PORT pid $(cat "$arm/pid")"
