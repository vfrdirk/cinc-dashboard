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
echo "==> building : ${SERVICES[*]} for linux/amd64,linux/arm64"

# Use docker buildx build to create and push multi-platform images.
# The --push flag builds and pushes to the registry in one step. It does not
# load the images into the local `docker images` list.
for svc in "${SERVICES[@]}"; do
  echo
  echo "--> building and pushing ${svc}"
  docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag "${REGISTRY}/cinc-dashboard-${svc}:${TAG}" \
    --push \
    "./${svc}"
done

echo
echo "==> published:"
for svc in "${SERVICES[@]}"; do
  printf '    %s/cinc-dashboard-%s:%s\n' "${REGISTRY}" "${svc}" "${TAG}"
done
echo
echo "To deploy elsewhere:"
echo "    docker compose pull && docker compose up -d"
