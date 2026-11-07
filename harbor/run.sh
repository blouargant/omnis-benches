#!/usr/bin/env bash
# Run omnis under Harbor on Terminal-Bench 2.1 / DeepSWE v1.1, Harness
# Leaderboard style (pinned task commits, same model for every agent, k attempts).
#
#   ./run.sh <tb|deepswe> <full|lean|full-noreview> [subset] [extra harbor args...]
#
# subset: smoke (the leaderboard's 3-task smoke subset, default) | pilot |
#         full | a comma list of task names.
# Knobs (env): MODEL (default openai/deepseek-v4.1-flash-scaleway),
#   IN_PRICE / OUT_PRICE / CACHE_PRICE ($/M), CONTEXT_LENGTH, ATTEMPTS (k, default 1),
#   CONCURRENCY (default 2), OMNIS_REPO / OMNIS_REF (omnis build), JOBS_DIR, JOB_NAME,
#   TIERED=1 (shipped model tiers, priced per agent; -m is then only the label),
#   SHAPE=<squad-bench/shapes.json arm> (squad-shape overlay in the user layer).
# Credentials: OPENAI_BASE_URL / OPENAI_API_KEY from the repo-root .env (single
# mechanism, see ../CLAUDE.md).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BENCH="${1:?usage: run.sh <tb|deepswe> <full|lean|full-noreview> [subset] [harbor args...]}"
VARIANT="${2:?variant full|lean|full-noreview}"
SUBSET="${3:-smoke}"
shift $(( $# >= 3 ? 3 : $# ))

[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${OPENAI_BASE_URL:?OPENAI_BASE_URL missing (root .env)}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY missing (root .env)}"
MODEL="${MODEL:-openai/deepseek-v4.1-flash-scaleway}"
IN_PRICE="${IN_PRICE:-0.63}"; OUT_PRICE="${OUT_PRICE:-1.89}"; CACHE_PRICE="${CACHE_PRICE:-0.126}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-229376}"
ATTEMPTS="${ATTEMPTS:-1}"; CONCURRENCY="${CONCURRENCY:-2}"
JOBS_DIR="${JOBS_DIR:-$HERE/jobs}"
CACHE="${OMNIS_HARBOR_CACHE:-$HOME/.cache/omnis-benches/harbor}"

command -v harbor >/dev/null || { echo "harbor not found: uv tool install 'harbor==0.24.0'" >&2; exit 2; }
docker compose version >/dev/null 2>&1 || { echo "docker compose (v2 plugin) is required by Harbor's docker environment" >&2; exit 2; }

TASKS_DIR="$("$HERE/fetch-tasks.sh" "$BENCH")"
mapfile -t NAMES < <(python3 "$HERE/subsets.py" "$BENCH" "$SUBSET")
INCLUDE=(); for n in "${NAMES[@]}"; do INCLUDE+=(-i "$n"); done

NET=()
if [[ "$BENCH" == deepswe ]]; then
  # DeepSWE's agent phase is no-network; let only the model gateway through
  # (the leaderboard does the same: offline except the inference route).
  HOST="$(python3 -c 'import sys,urllib.parse as u;print(u.urlparse(sys.argv[1]).hostname)' "$OPENAI_BASE_URL")"
  NET=(--allow-agent-host "$HOST")
  "$HERE/prebuild-sidecar.sh"   # the allowlist sidecar; no-op when buildx exists
fi

JOB_NAME="${JOB_NAME:-$BENCH-$VARIANT${SHAPE:+-$SHAPE}${TIERED:+-tiered}-$SUBSET-$(date +%Y%m%d-%H%M%S)}"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}" OMNIS_HARBOR_CACHE="$CACHE"
set -x
harbor run -p "$TASKS_DIR" "${INCLUDE[@]}" \
  -a omnis_harbor.agent:OmnisAgent \
  --ak "variant=$VARIANT" --ak "in_price=$IN_PRICE" --ak "out_price=$OUT_PRICE" \
  --ak "cache_price=$CACHE_PRICE" --ak "context_length=$CONTEXT_LENGTH" \
  ${TIERED:+--ak "tiered=true"} ${SHAPE:+--ak "shape=$SHAPE"} \
  ${OMNIS_REF:+--ak "omnis_ref=$OMNIS_REF"} ${OMNIS_REPO:+--ak "omnis_repo=$OMNIS_REPO"} \
  -m "$MODEL" -k "$ATTEMPTS" -n "$CONCURRENCY" "${NET[@]}" \
  -o "$JOBS_DIR" --job-name "$JOB_NAME" -y "$@"
set +x
python3 "$HERE/summarize.py" "$JOBS_DIR/$JOB_NAME"
