#!/usr/bin/env bash
# Run a task file one task at a time against an arm's server, stopping the arm
# as soon as budget.py says it costs over 1.5x the reference on the same tasks.
#   run-shape-arm.sh <port> <tasks.json> <out.jsonl> [ref.jsonl] [bench.py args...]
set -uo pipefail
PORT=${1:?port}; TASKS=${2:?tasks}; OUT=${3:?out}; REF=${4:-}; shift $(( $# >= 4 ? 4 : $# ))
HERE=$(cd "$(dirname "$0")" && pwd)
for id in $(python3 -c "import json,sys;print(' '.join(t['id'] for t in json.load(open(sys.argv[1]))['tasks']))" "$TASKS"); do
  python3 "$HERE/bench.py" --server "http://127.0.0.1:$PORT" --token bench --tasks "$TASKS" --task "$id" --out "$OUT" --json "$@" > /dev/null
  if [[ -n $REF ]] && ! python3 "$HERE/budget.py" stop --ref "$REF" --arm "$OUT"; then
    echo "early stop after $id"; break
  fi
done
