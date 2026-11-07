#!/usr/bin/env bash
# Build a static linux omnis CLI + its system config tree from a pinned omnis
# git ref, WITHOUT touching the omnis checkout (git archive → temp dir → go build).
#
#   OMNIS_REPO=../omnis OMNIS_REF=HEAD GOARCH=amd64 ./build-omnis.sh
#
# Output: $OMNIS_HARBOR_CACHE/omnis-<sha12>-<goarch>/{omnis,src.tar,VERSION}
# and prints that directory on stdout (last line). Idempotent: an existing
# build for the same sha is reused.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OMNIS_REPO="${OMNIS_REPO:-$HERE/../../omnis}"
OMNIS_REF="${OMNIS_REF:-HEAD}"
GOARCH="${GOARCH:-amd64}"
CACHE="${OMNIS_HARBOR_CACHE:-$HOME/.cache/omnis-benches/harbor}"

SHA="$(git -C "$OMNIS_REPO" rev-parse "$OMNIS_REF")"
DESC="$(git -C "$OMNIS_REPO" describe --tags --always "$SHA" 2>/dev/null || echo "$SHA")"
OUT="$CACHE/omnis-${SHA:0:12}-$GOARCH"
if [[ -x "$OUT/omnis" && -f "$OUT/src.tar" ]]; then echo "$OUT"; exit 0; fi

mkdir -p "$OUT"
SRC="$(mktemp -d)"; trap 'rm -rf "$SRC"' EXIT
git -C "$OMNIS_REPO" archive --format=tar "$SHA" > "$OUT/src.tar"
tar -xf "$OUT/src.tar" -C "$SRC"
(
  cd "$SRC"
  CGO_ENABLED=0 GOOS=linux GOARCH="$GOARCH" go build -trimpath \
    -ldflags "-s -w -X main.version=$DESC -X main.commit=$SHA" -o "$OUT/omnis" .
)
echo "$DESC $SHA" > "$OUT/VERSION"
echo "$OUT"
