#!/usr/bin/env bash
# Pre-build Harbor's egress-control sidecar image WITHOUT docker buildx.
#
# DeepSWE's agent phase is `no-network`; Harbor enforces the model-gateway
# allowlist with a sidecar image it builds via `docker buildx`. On a host with
# no buildx plugin that build fails ("unknown flag: --file") and every DeepSWE
# trial dies as an infra error. Harbor skips the build when the content-addressed
# tag already exists, so this script builds the identical image with the legacy
# builder under the exact tag Harbor computes. The only change is dropping
# `COPY --chmod=755` (BuildKit-only) — the copied files already carry mode 755.
# No-op when buildx is present or the image already exists.
set -euo pipefail
docker buildx version >/dev/null 2>&1 && exit 0
PY="$(dirname "$(readlink -f "$(command -v harbor)")")/python"
read -r CTX TAG < <("$PY" - <<'EOF'
import asyncio
from harbor.environments.docker.docker import DockerEnvironment as D
from harbor.environments.docker import utils as u
ctx = D._EGRESS_CONTROL_SIDECAR_CONTEXT_PATH
h = u.docker_build_context_hash(context=ctx, dockerfile_path=ctx / "Dockerfile", build_args={},
                                platform=asyncio.run(u.default_docker_platform()))
print(ctx, u._compute_image_name(D._EGRESS_CONTROL_SIDECAR_DOCKER_NAME, h))
EOF
)
docker image inspect "$TAG" >/dev/null 2>&1 && exit 0
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp -a "$CTX/." "$TMP/"
sed -i 's/^COPY --chmod=755 /COPY /' "$TMP/Dockerfile"
chmod 755 "$TMP/entrypoint.sh" "$TMP/bin/network-policy"
DOCKER_BUILDKIT=0 docker build -q -t "$TAG" "$TMP" >&2
echo "built $TAG" >&2
