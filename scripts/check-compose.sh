#!/bin/sh
# Validate every compose combination the repo ships (no containers are started).
# Used by CI and runnable locally: scripts/check-compose.sh
set -eu
cd "$(dirname "$0")/.."

export BIRDROMS_NFS_ADDR=192.0.2.10 BIRDROMS_NFS_EXPORT=/srv/roms

docker compose -f docker-compose.yml config -q
docker compose -f docker-compose.prod.yml config -q
docker compose -f docker-compose.prod.yml -f docker-compose.nfs.yml config -q
echo "compose files OK"
