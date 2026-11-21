#!/usr/bin/env bash
# Start / stop omnis-servers for the lessons-gain bench: one server per
# (arm, repetition), each with its own empty home, all on one build.
#   arms.sh start <workdir> <model> <reps> <base-port>   model: ref:<catalogue ref> | tiered
#   arms.sh stop  <workdir>
# Env: OMNIS_SRC (default ../../../omnis). Needs the gateway variables of ../../.env.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OMNIS_SRC=${OMNIS_SRC:-$(cd "$HERE/../../../omnis" && pwd)}
cmd=${1:?start|stop}; WORK=${2:?workdir}
if [[ $cmd == stop ]]; then
  for p in "$WORK"/*/pid; do [[ -f $p ]] && kill "$(cat "$p")" 2>/dev/null || true; done; exit 0
fi
MODEL=${3:?model}; REPS=${4:?reps}; PORT=${5:?base port}
mkdir -p "$WORK"; set -a; . "$HERE/../../.env"; set +a
[[ -x $WORK/omnis-server ]] || (cd "$OMNIS_SRC" && go build -o "$WORK/omnis-server" ./server && git rev-parse --short HEAD > "$WORK/commit")
sys=$WORK/sys; rm -rf "$sys"; mkdir -p "$sys"
cp -r "$OMNIS_SRC/config/"* "$sys/"; cp -r "$OMNIS_SRC/registry" "$sys/"
python3 - "$sys" "$MODEL" <<'PY'
import json, sys
d, model = sys.argv[1], sys.argv[2]
m = json.load(open(f"{d}/models.json"))
if model == "tiered":
    m["override_model_enabled"], m["embed_model_ref"] = False, ""
else:
    m["override_model_ref"], m["override_model_enabled"], m["embed_model_ref"] = model.split(":", 1)[1], True, ""
json.dump(m, open(f"{d}/models.json", "w"), indent=1)
PY
i=0
for arm in on off; do for rep in $(seq 1 "$REPS"); do
  d=$WORK/$arm-$rep; rm -rf "$d"; mkdir -p "$d/home"; port=$((PORT + i)); i=$((i + 1))
  echo '{"permissions":{"defaultMode":"bypassPermissions","allow":[],"ask":[],"deny":[]}}' > "$d/home/permissions.json"
  lessons=true; [[ $arm == off ]] && lessons=false
  env -u OMNIS_CONFIG_PATH OMNIS_HOME=$d/home HOME=$d/home OMNIS_SERVER_ADDR=127.0.0.1:$port OMNIS_SERVER_TOKEN=bench \
    OMNIS_UPDATE_CHECK=false OMNIS_NON_INTERACTIVE=1 OMNIS_TURN_MAX_TOKENS=0 OMNIS_TURN_MAX_TOOL_CALLS=0 \
    OMNIS_CONFIG_DIRS=$d/home:$sys OMNIS_SYSTEM_CONFIG_DIR=$sys OMNIS_AGENTSKILLS_DIR= OMNIS_LESSONS=$lessons \
    nohup "$WORK/omnis-server" --no-browser > "$d/server.log" 2>&1 &
  echo $! > "$d/pid"; echo "$port" > "$d/port"; echo "[$arm-$rep] port $port pid $(cat "$d/pid")"
done; done
