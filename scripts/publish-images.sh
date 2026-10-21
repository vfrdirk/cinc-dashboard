#!/usr/bin/env bash
# Build and publish the cinc-dashboard images to a container registry.
#
# Usage:
#   scripts/publish-images.sh                          # build + push :latest
#   CINC_IMAGE_TAG=v0.1.0 scripts/publish-images.sh    # build + push a version
#   CINC_REGISTRY=ghcr.io/myorg scripts/publish-images.sh
#
# Prerequisites:
#   docker login            # authenticated to $CINC_REGISTRY (default Docker Hub)
#   docker compose v2       # `docker compose`, not the legacy `docker-compose`
#
# Only the three custom images are published. `postgres` is an upstream official
# image and is pulled, never pushed.
set -euo pipefail

REGISTRY="${CINC_REGISTRY:-chunkylover59}"
TAG="${CINC_IMAGE_TAG:-latest}"
SERVICES=(collector api ui)

cd "$(dirname "$0")/.."

echo "==> registry : ${REGISTRY}"
echo "==> tag      : ${TAG}"
echo "==> building : ${SERVICES[*]}"

docker compose build "${SERVICES[@]}"

echo "==> pushing"
docker compose push "${SERVICES[@]}"

echo
echo "==> published:"
for svc in "${SERVICES[@]}"; do
  printf '    %s/cinc-dashboard-%s:%s\n' "${REGISTRY}" "${svc}" "${TAG}"
done
echo
echo "To deploy elsewhere:"
echo "    docker compose pull && docker compose up -d"
