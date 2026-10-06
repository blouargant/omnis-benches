#!/usr/bin/env bash
# Build the fixtures tasks-tokopt.json runs against, then export TOKOPT_DIR.
#   OMNIS_REPO=../omnis ./setup-tokopt.sh /tmp/tokopt
# Needs: git, go, cargo, npm, python3 (network for npm/pip installs).
set -euo pipefail
DIR=${1:?usage: setup-tokopt.sh <dir>}
OMNIS_REPO=${OMNIS_REPO:-$(cd "$(dirname "$0")/../../omnis" && pwd)}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$DIR"; DIR=$(cd "$DIR" && pwd)

# git/go tasks: a full-history clone pinned to the commit the expects were derived on.
rm -rf "$DIR/omnis-clone"
git clone -q --no-local "$OMNIS_REPO" "$DIR/omnis-clone"
git -C "$DIR/omnis-clone" checkout -q f2b3cf7

# go-fail: one deliberately failing test (Mul adds).
mkdir -p "$DIR/gofail"; cd "$DIR/gofail"
[ -f go.mod ] || go mod init example.com/gofail >/dev/null 2>&1
cat > calc.go <<'GO'
package calc

func Add(a, b int) int { return a + b }
func Mul(a, b int) int { return a + b } // bug
GO
cat > calc_test.go <<'GO'
package calc

import "testing"

func TestAdd(t *testing.T) { if Add(2, 3) != 5 { t.Fatal("add") } }
func TestMul(t *testing.T) {
	if got := Mul(2, 3); got != 6 {
		t.Errorf("Mul(2,3) = %d, want 6", got)
	}
}
func TestTable(t *testing.T) {
	for _, c := range []struct{ a, b, w int }{{1, 1, 2}, {2, 2, 4}, {3, 4, 7}} {
		t.Run("case", func(t *testing.T) { if Add(c.a, c.b) != c.w { t.Fail() } })
	}
}
GO

# rust-fail: one failing assertion (left 4, right 5).
rm -rf "$DIR/rs"; cd "$DIR" && cargo new -q rs
cat >> "$DIR/rs/src/main.rs" <<'RS'
#[cfg(test)]
mod tests { #[test] fn ok1(){assert_eq!(1,1)} #[test] fn bad(){assert_eq!(2+2,5)} }
RS
(cd "$DIR/rs" && cargo test -q >/dev/null 2>&1 || true)   # warm the build

# npm-deps / pip-ver: installed, so the task only has to list them.
mkdir -p "$DIR/js"; cd "$DIR/js"
echo '{"name":"x","version":"1.0.0"}' > package.json
npm install -q lodash express >/dev/null 2>&1
python3 -m venv "$DIR/venv"; "$DIR/venv/bin/pip" install -q requests

# TL variant: the lossless filter set (only meaningful on an omnis build that
# still ships config/filters — the feature was removed after this campaign).
if [ -d "$OMNIS_REPO/config/filters" ]; then
  python3 "$HERE/gen_lossless.py" "$OMNIS_REPO/config/filters" "$DIR/filters-lossless"
fi

echo "fixtures ready — export TOKOPT_DIR=$DIR"
echo "NOTE: npm/pip expects are pinned to express 5.2.1 / requests 2.x; re-check the versions installed."
