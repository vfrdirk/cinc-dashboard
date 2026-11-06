#!/usr/bin/env bash
set -euo pipefail
REGISTRY="${CINC_REGISTRY:-chunkylover59}"
TAG="${CINC_IMAGE_TAG:-latest}"
cd "$(dirname "$0")/.."
echo "==> registry : ${REGISTRY}"
echo "==> tag      : ${TAG}"
docker buildx build --platform linux/amd64,linux/arm64 --tag "${REGISTRY}/cinc-dashboard:${TAG}" --push "./app"
echo "==> published: ${REGISTRY}/cinc-dashboard:${TAG}"
