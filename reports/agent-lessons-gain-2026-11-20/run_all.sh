#!/usr/bin/env bash
# One full measurement: <reps> repetitions per arm, every repetition on its own
# server and empty home, all in parallel.
#   run_all.sh <workdir> <model> <reps> <base-port>      e.g. run_all.sh /tmp/gain-bal ref:balanced 5 18500
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${1:?workdir}; MODEL=${2:?model}; REPS=${3:?reps}; PORT=${4:?base port}
bash "$HERE/arms.sh" start "$WORK" "$MODEL" "$REPS" "$PORT"; sleep 5
pids=()
for d in "$WORK"/on-* "$WORK"/off-*; do
  n=$(basename "$d"); arm=${n%-*}; rep=${n#*-}
  python3 "$HERE/run_gain.py" --server "http://127.0.0.1:$(cat "$d/port")" --home "$d/home" --arm "$arm" --rep "$rep" \
    --model "$MODEL" --out "$WORK/runs-$n.jsonl" > "$WORK/log-$n.txt" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p" || true; done
bash "$HERE/arms.sh" stop "$WORK"
cat "$WORK"/runs-*.jsonl > "$WORK/runs.jsonl"; wc -l "$WORK/runs.jsonl"
