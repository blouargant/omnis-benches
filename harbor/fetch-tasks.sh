#!/usr/bin/env bash
# Clone a benchmark's task repo at the commit the Harness Leaderboard pins
# (hlb/data/benchmarks.json of the joelniklaus/harness-leaderboard Space) and
# print its tasks/ directory. Idempotent.
set -euo pipefail
CACHE="${OMNIS_HARBOR_CACHE:-$HOME/.cache/omnis-benches/harbor}"
case "${1:?tb|deepswe}" in
  tb)      NAME=tb21;    URL=https://github.com/harbor-framework/terminal-bench-2-1.git; REF=d49e28f1e4ddd13d289e85a5f312a66750951932 ;;
  deepswe) NAME=deepswe; URL=https://github.com/datacurve-ai/deep-swe.git;             REF=0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea ;;
  *) echo "unknown bench $1" >&2; exit 2 ;;
esac
D="$CACHE/$NAME"
if [[ ! -d "$D/.git" ]]; then
  mkdir -p "$CACHE"
  git clone -q --filter=blob:none "$URL" "$D" >&2
fi
if [[ "$(git -C "$D" rev-parse HEAD)" != "$REF" ]]; then
  git -C "$D" fetch -q origin "$REF" >&2 || true
  git -C "$D" checkout -q "$REF" >&2
fi
echo "$D/tasks"
