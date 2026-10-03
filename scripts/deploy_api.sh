#!/bin/bash
# Deploys one commit of the API image. The deploy key's forced command hands the
# client's command, through sudo, to this script as its only argument, so anything
# but one lowercase 40-character commit SHA is refused before a command runs. The
# explicit character set keeps the match independent of the locale.
set -euo pipefail

if [[ $# -ne 1 || ! $1 =~ ^[0123456789abcdef]{40}$ ]]; then
  echo "refused: expected one lowercase 40-character commit SHA" >&2
  exit 2
fi
sha=$1

echo "=== IDM Deploy $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
cd "${IDM_COMPOSE_DIR:-/opt/idm}"
# The compose file takes the image tag from IDM_API_TAG.
export IDM_API_TAG=$sha
docker compose pull idm-api
docker compose up -d --wait --wait-timeout 180 idm-api
echo "=== Health check ==="
curl -sf http://localhost:8000/health
echo ""
echo "=== Revision check ==="
cid=$(docker compose ps -q idm-api)
running=$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$cid")
echo "expected $sha, running $running"
test "$running" = "$sha"
# Unused images of this repository only; a rollback pulls its image again.
docker image prune -af --filter "label=org.opencontainers.image.source=https://github.com/coloursinvision/idm-generative-system"
echo "=== Deploy complete ==="
