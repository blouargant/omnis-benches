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
# The harness's task loader is FLAT (tasks/<id>/task.yaml); it errors on any
# top-level dir without a task.yaml — notably tasks/gatekeeper/, whose tasks are
# nested one level deeper. Point TASKS_DIR at tasks/gatekeeper to run that suite.
TASKS_DIR="${TASKS_DIR:-$KAB_DIR/tasks}"
CLUSTER_PROVIDER="${CLUSTER_PROVIDER:-kind}"
# The harness treats --concurrency 0 as "auto" = number of tasks, i.e. it runs
# EVERY task at once. That is wrong here: the kind path shares ONE cluster + ONE
# omnis-server, so parallel mutating tasks contend for the single node and flood
# the model endpoint → noisy, untrustworthy pass/fail. Default to sequential;
# override with CONCURRENCY=N only if you know the tasks are isolated enough.
CONCURRENCY="${CONCURRENCY:-1}"
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

# ---- run against omnis -------------------------------------------------------
mkdir -p "$OUTPUT_DIR"
export OMNIS_SERVER_BIN                       # omnis-agent uses this for isolation-mode tasks
export OMNIS_BENCH_SQUAD="${OMNIS_BENCH_SQUAD:-kubernetes}"

# omnis-server multiplexes many sessions, so we run ONE server for the whole run
# instead of one-per-task. It must be bound to the run's cluster kubeconfig, so
# run.sh owns the shared cluster's lifecycle (create here, DELETE on exit) and
# hands the harness a fixed --kubeconfig with --cluster-creation-policy DoNotCreate.
# Tasks that declare `isolation: cluster` (the gatekeeper suite) still get their
# own cluster from the harness; omnis-agent spawns a dedicated server for those
# (their kube-context differs from OMNIS_SHARED_CONTEXT). (kind only — for vcluster
# every task is isolated, so we keep the per-task-server path.)
SHARED_CLUSTER="${SHARED_CLUSTER:-k8s-ai-bench-eval}"   # matches the harness's name
SHARED_CONTEXT="kind-$SHARED_CLUSTER"
SHARED_KUBECONFIG="$OUTPUT_DIR/shared.kubeconfig"
SHARED_SERVER_HOME=""; SHARED_SERVER_PID=""

cleanup() {                                   # runs on EXIT; $? holds the exit code
  if [ -n "$SHARED_SERVER_PID" ] && kill -0 "$SHARED_SERVER_PID" 2>/dev/null; then
    echo ">> stopping shared omnis-server (pid $SHARED_SERVER_PID)"
    kill "$SHARED_SERVER_PID" 2>/dev/null || true
    wait "$SHARED_SERVER_PID" 2>/dev/null || true
  fi
  [ -n "$SHARED_SERVER_HOME" ] && rm -rf "$SHARED_SERVER_HOME"
  if [ "$CLUSTER_PROVIDER" = "kind" ] && [ "${KEEP_CLUSTER:-0}" != "1" ]; then
    echo ">> deleting kind cluster $SHARED_CLUSTER"
    kind delete cluster --name "$SHARED_CLUSTER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

CLUSTER_ARGS=()
if [ "$CLUSTER_PROVIDER" = "kind" ]; then
  if kind get clusters 2>/dev/null | grep -qx "$SHARED_CLUSTER"; then
    echo ">> reusing existing kind cluster $SHARED_CLUSTER"
  else
    echo ">> creating kind cluster $SHARED_CLUSTER"
    kind create cluster --name "$SHARED_CLUSTER"
  fi
  kind get kubeconfig --name "$SHARED_CLUSTER" > "$SHARED_KUBECONFIG"

  # start ONE shared omnis-server bound to the shared cluster
  SHARED_SERVER_HOME="$(mktemp -d)"
  cp "$HERE/bench-permissions.json" "$SHARED_SERVER_HOME/permissions.json"
  SHARED_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
  OMNIS_SERVER_URL="http://127.0.0.1:$SHARED_PORT"
  echo ">> starting shared omnis-server at $OMNIS_SERVER_URL (KUBECONFIG=$SHARED_CLUSTER)"
  OMNIS_HOME="$SHARED_SERVER_HOME" KUBECONFIG="$SHARED_KUBECONFIG" \
    OMNIS_SERVER_ADDR=":$SHARED_PORT" OMNIS_SERVER_TOKEN="" OMNIS_UPDATE_CHECK=false \
    "$OMNIS_SERVER_BIN" --no-browser >"$SHARED_SERVER_HOME/server.log" 2>&1 &
  SHARED_SERVER_PID=$!
  if ! python3 - "$OMNIS_SERVER_URL" <<'PY'
import sys, time, urllib.request
base = sys.argv[1]
for _ in range(90):
    try:
        urllib.request.urlopen(base + "/api/config/status", timeout=2); sys.exit(0)
    except Exception:
        time.sleep(0.5)
sys.exit(1)
PY
  then
    echo "shared omnis-server did not become ready; see $SHARED_SERVER_HOME/server.log" >&2
    exit 5
  fi
  export OMNIS_SERVER="$OMNIS_SERVER_URL"
  export OMNIS_SHARED_CONTEXT="$SHARED_CONTEXT"
  CLUSTER_ARGS=(--cluster-creation-policy DoNotCreate --kubeconfig "$SHARED_KUBECONFIG")
else
  unset OMNIS_SERVER                          # vcluster: every task isolated → per-task server
fi

echo ">> running k8s-ai-bench (agent = omnis; one shared server for the run)"
"$KAB_DIR/k8s-ai-bench" run \
  --agent-bin "$HERE/omnis-agent" \
  --tasks-dir "$TASKS_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --cluster-provider "$CLUSTER_PROVIDER" \
  --concurrency "$CONCURRENCY" \
  ${CLUSTER_ARGS[@]+"${CLUSTER_ARGS[@]}"} \
  --llm-provider "$LLM_PROVIDER" \
  --models "$MODEL" \
  ${TASK_PATTERN:+--task-pattern "$TASK_PATTERN"}

echo ">> done. results + JSONL under $OUTPUT_DIR (analyze with the harness's 'analyze' subcommand)."
