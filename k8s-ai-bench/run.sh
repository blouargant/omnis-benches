#!/usr/bin/env bash
#
# run.sh — run the gke-labs k8s-ai-bench suite against omnis.
#
# Pipeline:
#   1. Clone + build the upstream k8s-ai-bench harness (pinned).
#   2. Run it with `--agent-bin ./omnis-agent`. The harness spins up an ephemeral
#      kind cluster per task and hands each task's kubeconfig to omnis-agent, which
#      spawns a **dedicated throwaway omnis-server bound to that kubeconfig**,
#      drives the Kubernetes squad over HTTP, then tears the server down.
#      verify.sh scores Pass@k.
#
# Server lifecycle lives in omnis-agent (one server per task, KUBECONFIG = that
# task's ephemeral cluster), so this script only builds + launches the harness.
#
# Prerequisites (NOT auto-installed):
#   - docker + kind         (ephemeral clusters; --cluster-provider kind)
#   - kubectl, helm         (on PATH; omnis's tools shell out to them)
#   - go                    (to build k8s-ai-bench)
#   - omnis-server on PATH  (or set OMNIS_SERVER_BIN=/path/to/omnis-server)
#   - model credentials in the environment (whatever your omnis models.json reads,
#     e.g. OPENAI_BASE_URL / OPENAI_API_KEY) — source your omnis .env first.
#
# Usage:
#   source /path/to/omnis/.env        # model credentials
#   ./run.sh                          # all tasks
#   TASK_PATTERN='fix' ./run.sh       # subset (regex, e.g. 'fix', 'pod', 'scale')
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"          # omnis-benches project root

# ---- credentials: source the project-root .env (single mechanism) -----------
# Put OPENAI_BASE_URL / OPENAI_API_KEY (whatever the omnis models.json reads) in
# omnis-benches/.env. Sourced with auto-export so the values reach the
# omnis-server that omnis-agent spawns per task. Keys the .env sets override the
# current env; everything else passes through. .env is gitignored — never commit
# secrets. (source ../omnis/.env still works if you have the omnis checkout.)
if [ -f "$ROOT/.env" ]; then
  echo ">> sourcing $ROOT/.env"
  set -a
  # shellcheck source=/dev/null
  . "$ROOT/.env"
  set +a
fi

OMNIS_SERVER_BIN="${OMNIS_SERVER_BIN:-$(command -v omnis-server || true)}"
KAB_REPO="${KAB_REPO:-https://github.com/gke-labs/k8s-ai-bench}"
KAB_REF="${KAB_REF:-main}"          # pin a commit for reproducibility
KAB_DIR="${KAB_DIR:-$HERE/.k8s-ai-bench}"
OUTPUT_DIR="${OUTPUT_DIR:-$HERE/.build}"
TASK_PATTERN="${TASK_PATTERN:-}"
CLUSTER_PROVIDER="${CLUSTER_PROVIDER:-kind}"
# --llm-provider/--model are required by the harness but IGNORED by omnis-agent
# (omnis uses its own fleet); pass harmless placeholders.
LLM_PROVIDER="${LLM_PROVIDER:-openai}"
MODEL="${MODEL:-omnis}"

[ -n "$OMNIS_SERVER_BIN" ] || { echo "omnis-server not found; set OMNIS_SERVER_BIN" >&2; exit 1; }
command -v go >/dev/null   || { echo "go not found" >&2; exit 1; }
command -v kind >/dev/null || { echo "kind not found (needed for ephemeral clusters)" >&2; exit 1; }

# ---- build the upstream harness --------------------------------------------
if [ ! -d "$KAB_DIR/.git" ]; then
  git clone "$KAB_REPO" "$KAB_DIR"
fi
git -C "$KAB_DIR" fetch --quiet origin "$KAB_REF" && git -C "$KAB_DIR" checkout --quiet "$KAB_REF"
( cd "$KAB_DIR" && go build -o k8s-ai-bench . )

# ---- run against omnis (omnis-agent manages a server per task) --------------
mkdir -p "$OUTPUT_DIR"
echo ">> running k8s-ai-bench (agent = omnis; one dedicated server per task)"
export OMNIS_SERVER_BIN                       # omnis-agent uses this to spawn servers
export OMNIS_BENCH_SQUAD="${OMNIS_BENCH_SQUAD:-kubernetes}"
unset OMNIS_SERVER                            # force omnis-agent to spawn per task

"$KAB_DIR/k8s-ai-bench" run \
  --agent-bin "$HERE/omnis-agent" \
  --output-dir "$OUTPUT_DIR" \
  --cluster-provider "$CLUSTER_PROVIDER" \
  --llm-provider "$LLM_PROVIDER" \
  --models "$MODEL" \
  ${TASK_PATTERN:+--task-pattern "$TASK_PATTERN"}

echo ">> done. results + JSONL under $OUTPUT_DIR (analyze with the harness's 'analyze' subcommand)."
