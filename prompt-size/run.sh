#!/usr/bin/env bash
# Measure the fixed prompt (system instruction + tool declarations) of every
# omnis agent, from an omnis checkout's shipped config, with no model cost.
#   run.sh [OMNIS_DIR] [OUT_DIR]
set -euo pipefail
OMNIS=$(cd "${1:-../../omnis}" && pwd)
OUT=$(mkdir -p "${2:-out}" && cd "${2:-out}" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'kill $SRV 2>/dev/null || true; rm -rf "$WORK"' EXIT
PORT=${PORT:-18765}

# System layer = the checkout's config + registry; nothing else in the chain.
mkdir -p "$WORK/sys" "$WORK/home" "$WORK/cwd"
cp -r "$OMNIS"/config/* "$WORK/sys/"
ln -s "$OMNIS/registry" "$WORK/sys/registry"
[ -d "$OMNIS/softskills" ] && cp -r "$OMNIS/softskills" "$WORK/sys/softskills"
python3 - "$WORK/sys" "$PORT" <<'PY'
import json, sys
d, port = sys.argv[1], sys.argv[2]
m = json.load(open(f"{d}/models.json"))
m["providers"]["probe"] = {"kind": "openai_compat", "base_url": f"http://127.0.0.1:{port}/v1", "api_key": "x"}
m["models"]["probe"] = {"provider_ref": "probe", "model": "probe", "context_length": 200000}
m["override_model_ref"], m["override_model_enabled"], m["embed_model_ref"] = "probe", True, ""
json.dump(m, open(f"{d}/models.json", "w"))
p = json.load(open(f"{d}/permissions.json"))
p["permissions"]["defaultMode"] = "bypassPermissions"
json.dump(p, open(f"{d}/permissions.json", "w"))
PY
# A squad-shape overlay (squad-bench/shape_overlay.py) goes into the user layer.
[ -n "${OVERLAY:-}" ] && cp -r "$OVERLAY"/. "$WORK/home/"
ls "$OMNIS/registry/agents" > "$WORK/names"
(cd "$OMNIS" && go build -o "$WORK/omnis" .)
: > "$OUT/requests.jsonl"
python3 "$HERE/fake_server.py" "$PORT" "$OUT/requests.jsonl" "$WORK/names" & SRV=$!
sleep 0.5

squads=$(python3 -c "import json;print('\n'.join(s['name'] for s in json.load(open('$WORK/sys/agents.json'))['squads']))")
while IFS= read -r sq; do
  start="$sq"; [ "$sq" = "Omnis" ] && start=""
  echo "== $sq" >&2
  (cd "$WORK/cwd" && env -u OMNIS_CONFIG_PATH -u OMNIS_CONFIG_DIRS \
    OMNIS_HOME="$WORK/home" HOME="$WORK/home" OMNIS_SYSTEM_CONFIG_DIR="$WORK/sys" \
    OMNIS_AGENTSKILLS_DIR="" OMNIS_START_SQUAD="$start" OMNIS_NON_INTERACTIVE=1 \
    OMNIS_CURATOR_ENABLED=false \
    timeout 120 "$WORK/omnis" "PROBE-ROOT:$sq" >/dev/null 2>>"$OUT/omnis.stderr") || echo "   (exit $?)" >&2
done <<< "$squads"
python3 "$HERE/report.py" "$OUT/requests.jsonl" | tee "$OUT/report.txt"
